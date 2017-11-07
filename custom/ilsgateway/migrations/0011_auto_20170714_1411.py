# -*- coding: utf-8 -*-
# Generated by Django 1.10.7 on 2017-07-14 14:11
from __future__ import unicode_literals

from __future__ import absolute_import
import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ilsgateway', '0010_auto_20160830_1923'),
    ]

    operations = [
        migrations.AlterField(
            model_name='alert',
            name='date',
            field=models.DateTimeField(db_index=True),
        ),
        migrations.AlterField(
            model_name='organizationsummary',
            name='date',
            field=models.DateTimeField(db_index=True),
        ),
        migrations.AlterField(
            model_name='productavailabilitydata',
            name='date',
            field=models.DateTimeField(db_index=True),
        ),
        migrations.AlterField(
            model_name='supplypointstatus',
            name='status_date',
            field=models.DateTimeField(db_index=True, default=datetime.datetime.utcnow),
        ),
    ]
