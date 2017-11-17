# -*- coding: utf-8 -*-
# Generated by Django 1.10.7 on 2017-07-06 21:18
from __future__ import unicode_literals

from __future__ import absolute_import
from django.db import migrations

from corehq.form_processor.models import XFormInstanceSQL, XFormOperationSQL
from corehq.sql_db.operations import RawSQLMigration

migrator = RawSQLMigration(('corehq', 'sql_accessors', 'sql_templates'), {
    'FORM_STATE_DELETED': XFormInstanceSQL.DELETED,
    'FORM_STATE_ARCHIVED': XFormInstanceSQL.ARCHIVED,
    'FORM_STATE_NORMAL': XFormInstanceSQL.NORMAL,
    'FORM_OPERATION_ARCHIVE': XFormOperationSQL.ARCHIVE,
    'FORM_OPERATION_UNARCHIVE': XFormOperationSQL.UNARCHIVE,
})


class Migration(migrations.Migration):

    dependencies = [
        ('sql_accessors', '0054_drop_reindexa_accessor_functions'),
    ]

    operations = [
        migrator.get_migration('archive_unarchive_form2.sql'),
        migrator.get_migration('soft_delete_forms2.sql'),
        migrator.get_migration('soft_undelete_forms2.sql'),
    ]
