from django.db import models

from dimagi.utils.couch import CriticalSection


PROPERTY_TYPE_CHOICES = (
    ('date', 'Date'),
    ('plain', 'Plain'),
    ('number', 'Number'),
    ('select', 'Select'),
    ('audio', 'Audio'),
    ('barcode', 'Barcode'),
    ('gps', 'GPS'),
    ('image', 'Image'),
    ('phone_number', 'Phone Number'),
    ('password', 'Password'),
    ('signature', 'Signature'),
    ('video', 'Video'),
    ('balance', 'Balance'),
    ('transfer', 'Transfer'),
    ('dispense', 'Dispense'),
    ('receive', 'Receive'),
    ('save_to_case', 'Save To Case'),
    ('', 'No Type Currently Selected')
)


class CaseType(models.Model):
    domain = models.CharField(max_length=255, default=None)
    name = models.CharField(max_length=255, default=None)
    description = models.TextField(default='', blank=True)
    fully_generated = models.BooleanField(default=False)

    class Meta:
        unique_together = ('domain', 'name')

    @classmethod
    def get_or_create(cls, domain, case_type):
        key = 'data-dict-case-type-{domain}-{type}'.format(
            domain=domain, type=case_type
        )
        with CriticalSection([key]):
            try:
                case_type_obj = CaseType.objects.get(domain=domain, name=case_type)
            except CaseType.DoesNotExist:
                case_type_obj = CaseType.objects.create(domain=domain, name=case_type)
            return case_type_obj


class CaseProperty(models.Model):
    case_type = models.ForeignKey(
        CaseType,
        on_delete=models.CASCADE,
        related_name='properties',
        related_query_name='property'
    )
    name = models.CharField(max_length=255, default=None)
    description = models.TextField(default='', blank=True)
    deprecated = models.BooleanField(default=False)
    data_type = models.CharField(
        choices=PROPERTY_TYPE_CHOICES,
        max_length=20,
        default='',
        blank=True
    )
    group = models.TextField(default='', blank=True)

    class Meta:
        unique_together = ('case_type', 'name')

    @classmethod
    def get_or_create(cls, name, case_type, domain):
        key = 'data-dict-property-{domain}-{type}-{name}'.format(
            domain=domain, type=case_type, name=name
        )
        with CriticalSection([key]):
            try:
                prop = CaseProperty.objects.get(
                    name=name, case_type__name=case_type, case_type__domain=domain
                )
            except CaseProperty.DoesNotExist:
                case_type_obj = CaseType.get_or_create(domain, case_type)
                prop = CaseProperty.objects.create(case_type=case_type_obj, name=name)
            return prop
