from __future__ import absolute_import
import math
from datetime import datetime, timedelta
from celery.task import task
from corehq.apps.sms.mixin import (InvalidFormatException,
    PhoneNumberInUseException, PhoneNumberException, CommCareMobileContactMixin,
    apply_leniency)
from corehq.apps.sms.models import (OUTGOING, INCOMING, SMS,
    PhoneLoadBalancingMixin, QueuedSMS, PhoneNumber, MigrationStatus)
from corehq.apps.sms.api import (send_message_via_backend, process_incoming,
    log_sms_exception, create_billable_for_sms, get_utcnow)
from django.db import transaction, DataError
from django.conf import settings
from corehq import privileges
from corehq.apps.accounting.utils import domain_has_privilege
from corehq.apps.domain.models import Domain
from corehq.apps.smsbillables.exceptions import RetryBillableTaskException
from corehq.apps.smsbillables.models import SmsBillable
from corehq.apps.sms.change_publishers import publish_sms_saved
from corehq.apps.sms.util import is_contact_active
from corehq.apps.users.models import CouchUser, CommCareUser
from corehq.form_processor.interfaces.dbaccessors import CaseAccessors
from corehq.toggles import RETRY_SMS_INDEFINITELY
from corehq.util.celery_utils import no_result_task
from corehq.util.timezones.conversions import ServerTime
from dimagi.utils.couch.cache.cache_core import get_redis_client
from dimagi.utils.couch import release_lock, CriticalSection
from dimagi.utils.rate_limit import rate_limit


def remove_from_queue(queued_sms):
    with transaction.atomic():
        sms = SMS()
        for field in sms._meta.fields:
            if field.name != 'id':
                setattr(sms, field.name, getattr(queued_sms, field.name))
        queued_sms.delete()
        sms.save()

    sms.publish_change()

    if sms.direction == OUTGOING and sms.processed and not sms.error:
        create_billable_for_sms(sms)
    elif sms.direction == INCOMING and sms.domain and domain_has_privilege(sms.domain, privileges.INBOUND_SMS):
        create_billable_for_sms(sms)


def handle_unsuccessful_processing_attempt(msg):
    msg.num_processing_attempts += 1
    if msg.num_processing_attempts < settings.SMS_QUEUE_MAX_PROCESSING_ATTEMPTS:
        delay_processing(msg, settings.SMS_QUEUE_REPROCESS_INTERVAL)
    elif msg.direction == OUTGOING and RETRY_SMS_INDEFINITELY.enabled(msg.domain):
        delay_processing(msg, settings.SMS_QUEUE_REPROCESS_INDEFINITELY_INTERVAL)
    else:
        msg.set_system_error(SMS.ERROR_TOO_MANY_UNSUCCESSFUL_ATTEMPTS)
        remove_from_queue(msg)


def handle_successful_processing_attempt(msg):
    utcnow = get_utcnow()
    msg.num_processing_attempts += 1
    msg.processed = True
    msg.processed_timestamp = utcnow
    if msg.direction == OUTGOING:
        msg.date = utcnow
    msg.save()
    remove_from_queue(msg)


def delay_processing(msg, minutes):
    msg.datetime_to_process += timedelta(minutes=minutes)
    msg.save()


def get_lock(client, key):
    return client.lock(key, timeout=settings.SMS_QUEUE_PROCESSING_LOCK_TIMEOUT*60)


def time_within_windows(domain_now, windows):
    weekday = domain_now.weekday()
    time = domain_now.time()

    for window in windows:
        if (window.day in [weekday, -1] and
            (window.start_time is None or time >= window.start_time) and
            (window.end_time is None or time <= window.end_time)):
            return True

    return False


def handle_domain_specific_delays(msg, domain_object, utcnow):
    """
    Checks whether or not we need to hold off on sending an outbound message
    due to any restrictions set on the domain, and delays processing of the
    message if necessary.

    Returns True if a delay was made, False if not.
    """
    domain_now = ServerTime(utcnow).user_time(domain_object.get_default_timezone()).done()

    if len(domain_object.restricted_sms_times) > 0:
        if not time_within_windows(domain_now, domain_object.restricted_sms_times):
            delay_processing(msg, settings.SMS_QUEUE_DOMAIN_RESTRICTED_RETRY_INTERVAL)
            return True

    if msg.chat_user_id is None and len(domain_object.sms_conversation_times) > 0:
        if time_within_windows(domain_now, domain_object.sms_conversation_times):
            sms_conversation_length = domain_object.sms_conversation_length
            conversation_start_timestamp = utcnow - timedelta(minutes=sms_conversation_length)
            if SMS.inbound_entry_exists(
                msg.couch_recipient_doc_type,
                msg.couch_recipient,
                conversation_start_timestamp,
                to_timestamp=utcnow
            ):
                delay_processing(msg, 1)
                return True

    return False


def message_is_stale(msg, utcnow):
    oldest_allowable_datetime = \
        utcnow - timedelta(hours=settings.SMS_QUEUE_STALE_MESSAGE_DURATION)
    if isinstance(msg.date, datetime):
        return msg.date < oldest_allowable_datetime
    else:
        return True


def connection_slot_key_base(backend):
    return 'backend-%s-connection-slot-' % backend.couch_id


def reserve_connection_slot(backend, max_simultaneous_connections):
    """
    There is one redis key per connection slot, numbered from 1 to
    max_simultaneous_connections.
    A slot is considered taken if the corresponding redis key exists,
    or is considered free if it does not exist.
    """
    with CriticalSection(['reserve-connection-slot-for-%s' % backend.couch_id]):
        client = get_redis_client()
        key_base = connection_slot_key_base(backend)
        slot_keys = client.keys(key_base + '*')
        reserved_slots = [slot_key.replace(key_base, '') for slot_key in slot_keys]

        for slot_number in range(1, max_simultaneous_connections + 1):
            slot_string = str(slot_number)
            if slot_string not in reserved_slots:
                key = key_base + slot_string
                client.set(key, 1)
                client.expire(key, 60)
                return slot_string

    return None


def free_connection_slot(backend, slot):
    client = get_redis_client()
    client.delete(connection_slot_key_base(backend) + slot)


def handle_outgoing(msg):
    """
    Should return a requeue flag, so if it returns True, the message will be
    requeued and processed again immediately, and if it returns False, it will
    not be queued again.
    """
    backend = msg.outbound_backend
    sms_rate_limit = backend.get_sms_rate_limit()
    use_rate_limit = sms_rate_limit is not None
    use_load_balancing = isinstance(backend, PhoneLoadBalancingMixin)
    max_simultaneous_connections = backend.get_max_simultaneous_connections()
    orig_phone_number = None

    if use_load_balancing:
        orig_phone_number = backend.get_next_phone_number(msg.phone_number)

    if use_rate_limit:
        if use_load_balancing:
            redis_key = 'sms-rate-limit-backend-%s-phone-%s' % (backend.pk, orig_phone_number)
        else:
            redis_key = 'sms-rate-limit-backend-%s' % backend.pk

        if not rate_limit(redis_key, actions_allowed=sms_rate_limit, how_often=60):
            # Requeue the message and try it again shortly
            return True

    if max_simultaneous_connections:
        connection_slot = reserve_connection_slot(backend, max_simultaneous_connections)
        if not connection_slot:
            # Requeue the message and try it again shortly
            return True

    result = send_message_via_backend(
        msg,
        backend=backend,
        orig_phone_number=orig_phone_number
    )

    if max_simultaneous_connections:
        free_connection_slot(backend, connection_slot)

    if msg.error:
        remove_from_queue(msg)
    else:
        # Only do the following if an unrecoverable error did not happen
        if result:
            handle_successful_processing_attempt(msg)
        else:
            handle_unsuccessful_processing_attempt(msg)

    return False


def handle_incoming(msg):
    try:
        process_incoming(msg)
        handle_successful_processing_attempt(msg)
    except:
        log_sms_exception(msg)
        handle_unsuccessful_processing_attempt(msg)


@no_result_task(queue="sms_queue", acks_late=True)
def process_sms(queued_sms_pk):
    """
    queued_sms_pk - pk of a QueuedSMS entry
    """
    client = get_redis_client()
    utcnow = get_utcnow()
    # Prevent more than one task from processing this SMS, just in case
    # the message got enqueued twice.
    message_lock = get_lock(client, "sms-queue-processing-%s" % queued_sms_pk)

    if message_lock.acquire(blocking=False):
        try:
            msg = QueuedSMS.objects.get(pk=queued_sms_pk)
        except QueuedSMS.DoesNotExist:
            # The message was already processed and removed from the queue
            release_lock(message_lock, True)
            return

        if message_is_stale(msg, utcnow):
            msg.set_system_error(SMS.ERROR_MESSAGE_IS_STALE)
            remove_from_queue(msg)
            release_lock(message_lock, True)
            return

        if msg.direction == OUTGOING:
            if msg.domain:
                domain_object = Domain.get_by_name(msg.domain)
            else:
                domain_object = None
            if domain_object and handle_domain_specific_delays(msg, domain_object, utcnow):
                release_lock(message_lock, True)
                return

        requeue = False
        # Process inbound SMS from a single contact one at a time
        recipient_block = msg.direction == INCOMING
        if (isinstance(msg.processed, bool)
            and not msg.processed
            and not msg.error
            and msg.datetime_to_process < utcnow):
            if recipient_block:
                recipient_lock = get_lock(client, 
                    "sms-queue-recipient-phone-%s" % msg.phone_number)
                recipient_lock.acquire(blocking=True)

            if msg.direction == OUTGOING:
                if (
                    msg.domain and
                    msg.couch_recipient_doc_type and
                    msg.couch_recipient and
                    not is_contact_active(msg.domain, msg.couch_recipient_doc_type, msg.couch_recipient)
                ):
                    msg.set_system_error(SMS.ERROR_CONTACT_IS_INACTIVE)
                    remove_from_queue(msg)
                else:
                    requeue = handle_outgoing(msg)
            elif msg.direction == INCOMING:
                handle_incoming(msg)
            else:
                msg.set_system_error(SMS.ERROR_INVALID_DIRECTION)
                remove_from_queue(msg)

            if recipient_block:
                release_lock(recipient_lock, True)

        release_lock(message_lock, True)
        if requeue:
            process_sms.delay(queued_sms_pk)


@no_result_task(default_retry_delay=10 * 60, max_retries=10, bind=True)
def store_billable(self, msg):
    if not isinstance(msg, SMS):
        raise Exception("Expected msg to be an SMS")

    if msg.couch_id and not SmsBillable.objects.filter(log_id=msg.couch_id).exists():
        try:
            msg.text.encode('iso-8859-1')
            msg_length = 160
        except UnicodeEncodeError:
            # This string contains unicode characters, so the allowed
            # per-sms message length is shortened
            msg_length = 70
        try:
            SmsBillable.create(
                msg,
                multipart_count=int(math.ceil(float(len(msg.text)) / msg_length)),
            )
        except RetryBillableTaskException as e:
            self.retry(exc=e)
        except DataError:
            from corehq.util.soft_assert import soft_assert
            _soft_assert = soft_assert(to='{}@{}'.format('jemord', 'dimagi.com'))
            _soft_assert(len(msg.domain) < 25, "Domain name too long: " + msg.domain)
            raise


@no_result_task(queue='background_queue', acks_late=True)
def delete_phone_numbers_for_owners(owner_ids):
    for p in PhoneNumber.objects.filter(owner_id__in=owner_ids):
        # Clear cache and delete
        p.delete()


def clear_case_caches(case):
    from corehq.apps.sms.util import is_case_contact_active
    is_case_contact_active.clear(case.domain, case.case_id)


@no_result_task(queue=settings.CELERY_REMINDER_CASE_UPDATE_QUEUE, acks_late=True,
                default_retry_delay=5 * 60, max_retries=10, bind=True)
def sync_case_phone_number(self, case):
    try:
        clear_case_caches(case)
        _sync_case_phone_number(case)
    except Exception as e:
        self.retry(exc=e)


def _sync_case_phone_number(contact_case):
    phone_info = contact_case.get_phone_info()

    with CriticalSection([contact_case.phone_sync_key], timeout=5 * 60):
        phone_numbers = contact_case.get_phone_entries()

        if len(phone_numbers) == 0:
            phone_number = None
        elif len(phone_numbers) == 1:
            phone_number = list(phone_numbers.values())[0]
        else:
            # We use locks to make sure this scenario doesn't happen, but if it
            # does, just clear the phone number entries and the right one will
            # be recreated below.
            for p in phone_numbers.values():
                p.delete()
            phone_number = None

        if (
            phone_number and
            phone_number.contact_last_modified and
            phone_number.contact_last_modified >= contact_case.server_modified_on
        ):
            return

        if not phone_info.requires_entry:
            if phone_number:
                phone_number.delete()
            return

        if phone_number and phone_number.phone_number != phone_info.phone_number:
            phone_number.delete()
            phone_number = None

        if not phone_number:
            phone_number = contact_case.create_phone_entry(phone_info.phone_number)

        phone_number.backend_id = phone_info.sms_backend_id
        phone_number.ivr_backend_id = phone_info.ivr_backend_id
        phone_number.contact_last_modified = contact_case.server_modified_on

        if phone_info.qualifies_as_two_way:
            try:
                phone_number.set_two_way()
                phone_number.set_verified()
            except PhoneNumberInUseException:
                pass
        else:
            phone_number.is_two_way = False
            phone_number.verified = False
            phone_number.pending_verification = False

        phone_number.save()


@no_result_task(queue=settings.CELERY_REMINDER_CASE_UPDATE_QUEUE, acks_late=True,
                default_retry_delay=5 * 60, max_retries=10, bind=True)
def sync_user_phone_numbers(self, couch_user_id):
    try:
        _sync_user_phone_numbers(couch_user_id)
    except Exception as e:
        self.retry(exc=e)


def _sync_user_phone_numbers(couch_user_id):
    couch_user = CouchUser.get_by_user_id(couch_user_id)

    if not isinstance(couch_user, CommCareUser):
        # It isn't necessary to sync WebUser's phone numbers right now
        # and we need to think through how to support entries when a user
        # can belong to multiple domains
        return

    with CriticalSection([couch_user.phone_sync_key], timeout=5 * 60):
        phone_entries = couch_user.get_phone_entries()

        if couch_user.is_deleted():
            for phone_number in phone_entries.values():
                phone_number.delete()
            return

        numbers_that_should_exist = [apply_leniency(phone_number) for phone_number in couch_user.phone_numbers]

        # Delete entries that should not exist
        for phone_number in phone_entries.keys():
            if phone_number not in numbers_that_should_exist:
                phone_entries[phone_number].delete()

        # Create entries that should exist but do not exist
        for phone_number in numbers_that_should_exist:
            if phone_number not in phone_entries:
                try:
                    couch_user.create_phone_entry(phone_number)
                except InvalidFormatException:
                    pass


@no_result_task(queue='background_queue', acks_late=True,
                default_retry_delay=5 * 60, max_retries=10, bind=True)
def publish_sms_change(self, sms):
    try:
        publish_sms_saved(sms)
    except Exception as e:
        self.retry(exc=e)


@no_result_task(queue='background_queue')
def sync_phone_numbers_for_domain(domain):
    for user_id in CouchUser.ids_by_domain(domain, is_active=True):
        _sync_user_phone_numbers(user_id)

    for user_id in CouchUser.ids_by_domain(domain, is_active=False):
        _sync_user_phone_numbers(user_id)

    case_ids = CaseAccessors(domain).get_case_ids_in_domain()
    for case in CaseAccessors(domain).iter_cases(case_ids):
        _sync_case_phone_number(case)

    MigrationStatus.set_migration_completed('phone_sync_domain_%s' % domain)
