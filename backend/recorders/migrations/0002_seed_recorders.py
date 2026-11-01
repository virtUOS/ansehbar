# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""No-op: the seed data moved to the site configuration (see README).

The migration is kept so that existing databases stay consistent. Recorders
are now loaded with `manage.py load_site_config` from a local JSON file.
"""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("recorders", "0001_initial")]

    operations = []
