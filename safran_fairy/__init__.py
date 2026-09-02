# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn the Météo-France SIM2 reanalysis into one NetCDF per climate variable.

Source: « Données changement climatique SIM quotidienne » on data.gouv.fr
        https://www.data.gouv.fr/datasets/6569b27598256cc583c917a7

Typical use:

    from safran_fairy import build, check

    outputs = build("03_data-convert", "04_data-output", variables=["TINF_H"])
    rejected = check(outputs)          # must be empty before publishing
"""

from .sources import (Resource, check_inventory, data_resources, describe,
                      is_data_filename,
                      list_resources)
from .download import download
from .decompress import decompress
from .split import split
from .convert import convert
from .build import build, inventory
from .check import check, check_file
from .clean import clean_local, clean_s3
from .tools import build_filename, parse_filename
from .upload_s3 import (apply_s3_bucket_cors, apply_s3_bucket_policy,
                        delete_s3_files, list_s3_files, upload_s3)
from .catalog import generate_stac_catalog

__all__ = [
    "Resource", "list_resources", "data_resources", "describe",
    "check_inventory", "is_data_filename",
    "download", "decompress", "split", "convert", "build", "check",
    "check_file", "inventory",
    "clean_local", "clean_s3",
    "parse_filename", "build_filename",
    "apply_s3_bucket_policy", "apply_s3_bucket_cors", "list_s3_files",
    "upload_s3", "delete_s3_files",
    "generate_stac_catalog",
]
