#!/usr/bin/env python3

import io, struct, sys, os
import json
import re
import string
import logging
import glob
import pydicom


logging.basicConfig()
log = logging.getLogger('ptd_parser')


def ptd_reader(filepath):
    """
    A function for reading in valid *.ptd files
    Written by Gunnar Schaefer

    :param filepath: path to the ptd file
    :type filepath: str
    :returns:  pydicom object representing the ptd header
    """

    MAGIC_STR = b'LARGE_PET_LM_RAWDATA'
    MAGIC_STR_LEN = len(MAGIC_STR)

    fp = open(filepath, 'rb')

    fp.seek(-MAGIC_STR_LEN, 2)

    if fp.read(MAGIC_STR_LEN) != MAGIC_STR:
        print('ERROR: This is not a .ptd file.')
        sys.exit(1)

    fp.seek(-MAGIC_STR_LEN - struct.calcsize('i'), 2)
    offset = struct.unpack('i', fp.read(struct.calcsize('i')))[0]
    fp.seek(-offset - MAGIC_STR_LEN - struct.calcsize('i'), 2)
    dcm_buf = io.BytesIO(fp.read(offset))
    fp.close()
    ptd = pydicom.read_file(dcm_buf)
    return ptd


def assign_type(s):
    """
    Sets the type of a given input.
    """
    if type(s) == pydicom.valuerep.PersonName or type(s) == pydicom.valuerep.PersonName3 or type(
            s) == pydicom.valuerep.PersonNameBase:
        return format_string(s)
    if type(s) == list or type(s) == pydicom.multival.MultiValue:
        try:
            return [int(x) for x in s]
        except ValueError:
            try:
                return [float(x) for x in s]
            except ValueError:
                return [format_string(x) for x in s if len(x) > 0]
    else:
        s = str(s)
        try:
            return int(s)
        except ValueError:
            try:
                return float(s)
            except ValueError:
                return format_string(s)


def format_string(in_string):
    formatted = re.sub(r'[^\x00-\x7f]', r'', str(in_string))  # Remove non-ascii characters
    formatted = ''.join(filter(lambda x: x in string.printable, formatted))
    if (len(formatted) == 1 and formatted == '?') or len(formatted) == 0:
        formatted = None
    return formatted


def get_seq_data(sequence, ignore_keys):
    seq_dict = {}
    for seq in sequence:
        for s_key in seq.dir():
            s_val = getattr(seq, s_key, '')
            if type(s_val) is pydicom.UID.UID or s_key in ignore_keys:
                continue

            if type(s_val) == pydicom.sequence.Sequence:
                _seq = get_seq_data(s_val, ignore_keys)
                seq_dict[s_key] = _seq
                continue

            if type(s_val) == str:
                s_val = format_string(s_val)
            else:
                s_val = assign_type(s_val)

            if s_val:
                seq_dict[s_key] = s_val

    return seq_dict


def parse_header(ptd):
    # Extract the header values
    header = {}
    exclude_tags = ['[Unknown]', 'PixelData', 'Pixel Data', '[User defined data]', '[Protocol Data Block (compressed)]',
                    '[Histogram tables]', '[Unique image iden]']
    tags = ptd.dir()
    for tag in tags:
        formatted = None
        try:
            if (tag not in exclude_tags) and (type(ptd.get(tag)) != pydicom.sequence.Sequence):
                value = ptd.get(tag)
                if value or value == 0:  # Some values are zero
                    # Put the value in the header
                    if type(value) == str and len(value) < 10240:  # Max dicom field length
                        formatted = format_string(value)
                    else:
                        formatted = assign_type(value)
                else:
                    log.debug('No value found for tag: ' + tag)
            if formatted:
                header[tag] = formatted
            if type(ptd.get(tag)) == pydicom.sequence.Sequence:
                seq_data = get_seq_data(ptd.get(tag), exclude_tags)
                # Check that the sequence is not empty
                if seq_data:
                    header[tag] = seq_data
        except:
            log.debug('Failed to get ' + tag)
            pass
    return header


# Gear basics
input_folder = '/flywheel/v0/input/file/'
output_folder = '/flywheel/v0/output/'

# declare config file path
config_file_path = '/flywheel/v0/config.json'

with open(config_file_path) as config_data:
    config = json.load(config_data)

# get PET file path and name from config
ptd_file = config['inputs']['ptd_file']['location']['path']
ptd_name = config['inputs']['ptd_file']['location']['name']

# Declare the output path
output_filepath = os.path.join(output_folder, '.metadata.json')

# determine the level from which the gear was invoked
hierarchy_level = config['inputs']['ptd_file']['hierarchy']['type']

# read custom label from config
custom_label = config['config']['custom_label']

# prepare object for .metadata.json file
metadata_json_out = {
    hierarchy_level: {
        "files": []
    }
}

PET_dict = {
    "name": ptd_name,
    "info": {
        "dicom": {}
    },
    "modality": "PT"
    #"file-type": "PTD"
}

# check if file is actually .ptd
if ptd_file.endswith(".ptd"):
    log.info("Reading PET file: {}".format(ptd_name))
    # read in ptd file header
    ptd = ptd_reader(ptd_file)
    # parse ptd file header
    log.info("Parsing PET file: {}".format(ptd_name))
    ptd_header = parse_header(ptd)
    # append header to metadata object
    file_name = os.path.splitext(ptd_name)[0]
    PET_dict['info']['dicom'] = ptd_header
    metadata_json_out[hierarchy_level]["files"].append(PET_dict)
    log.info("Saving PET file header to .metadata.json:{}".format(metadata_json_out))
    with open(output_filepath, 'w') as outfile:
        json.dump(metadata_json_out, outfile, separators=(', ', ': '), sort_keys=True, indent=4)
else:
    log.error("The provided file is not a PET file")
    sys.exit(1)
