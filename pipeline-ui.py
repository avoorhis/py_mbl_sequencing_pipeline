#!/usr/bin/env python
#!/usr/local/www/vamps/software/python/bin/python

##!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (C) 2011, Marine Biological Laboratory
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# Please read the COPYING file.
#

import os
from stat import * # ST_SIZE etc
import sys
import shutil
import types
from time import sleep
from pipeline.utils import *
from pipeline.sample import Sample
from pipeline.runconfig import RunConfig
from pipeline.run import Run
from pipeline.chimera import Chimera
from pipeline.gast import Gast
from pipeline.metadata import MetadataUtils
from pipeline.pipelinelogging import logger
from pipeline.trim_run import TrimRun
from pipeline.get_ini import readCSV

import logging
import argparse
from pipelineprocessor import process
import pprint

# pycogent
# import cogent

import pipeline.constants as C
# read a config file and convert to a dictionary



if __name__ == '__main__':
    # usage = """
    #     usage: ./pipeline-ui.py [options]
    #
    #         options:
    #             -c/--configuration      configuration file with path  [required]
    #
    #             -f/--config_format      configuration file format: csv or ini [optional (default:csv)]
    #
    #             -p/--platform           Platform: illumina, 454 or ion_torrent [required]
    #
    #             -i/--input_directory    Directory where sequence files can be found [optional (default: ./)]
    #
    #             -r/--run                Run - number or date  [required]
    #
    #             -ft/--seq_file_type     File type for sequences: fasta, fastq or sff
    #                                         [optional (default: fasta)]
    #
    #             -fs/--seq_file_suffix   File suffix - useful when there are additional files
    #                                         in the input directory that you don't want to include. [optional (default: fa.unique)]
    #             -archaea/--archaea               For illumina only [optional (default: "")]
    #
    #             -s/--steps              Steps to be performed by this pipeline (comma separated list)
    #                                         Choices:    validate        - validates your metadata file
    #                                                     status          - prints out status messages if any
    #                                                     trim            - trims your sequences
    #                                                     chimera         - performs chimera check on trimmed sequences
    #                                                     upload_env454   - Load data into the env454 database
    #                                                     gast            - assign taxonomy to the trimmed sequences using GAST
    #                                                     upload_vamps    - load sequences and taxonomy to VAMPS
    #                                                     clean           - removes run from database and filesystem
    #
    #             -l/--loglevel           Change the level of logging: info, debug, error   [optional (default: error)]
    #
    #     """
    # """
    # not use, remove!
    #                 -b/--baseoutputdir       Base output directory where the run directory will be found.
    #                                         The run directory will be created if it is not found.  [optional (default: ./)]
    # """

    # if  len(sys.argv) == 1:
    #     print(usage)
    #     sys.exit()
    #THE_DEFAULT_BASE_OUTPUT = '.'

    # required items: configuration file, run and platform only
    # NO DEFAULTS HERE: DO Not give items defaults here as the script needs to look in the ini file as well
    # except steps (status) and loglevel (error) and
    # see metadata.py and constants.py:  get_command_line_items()
    # BUT general section of ini file must have important things not supplied on command line
    # which means that csv file will require more commandline parameters.
    # NOTE: do not store any of the command line item as store_true or store_false or they
    # may not be able to be overridden buy the config file (ini).
    """TO add a new argument:
        1) add it here
        2) add it to constants.pipeline_run_items()
        3) add it to runconfig.initializeFromDictionary()
    """
    parser = argparse.ArgumentParser(description='MBL Sequence Pipeline')
    parser.add_argument('-c', '--configuration', required=False,                         dest = "configPath",
                                                 help = 'Configuration parameters (.ini file) of the run. See README File')
    parser.add_argument("-r", "--run",     required=True,  action="store",              dest = "run",
                                                    help="unique run number ")


    parser.add_argument("-s", "--steps",     required=False,  action="store",           dest = "steps",            default = 'status',
                                                help="""
                                                Comma seperated list of steps.
                                                Choices are: validate,trim,chimera,status,upload_env454,gast,otu,upload_vamps,clean
                                                """)
    parser.add_argument("-p", "--platform",     required=True,  action="store",         dest = "platform",
                                                    help="Platform: illumina, 454, ion_torrent, or vamps ")
    ####################################################################################################################
    parser.add_argument('-l', '--loglevel',  required=False,   action="store",          dest = "loglevel",          default='ERROR',
                                                 help = 'Sets logging level... DEBUG, [INFO], WARNING, ERROR, CRITICAL')

    parser.add_argument("-i", "--input_directory",     required=False,  action="store", dest = "input_dir",
                                                    help="Directory where sequence files can be found. ")
    ####################################################################################################################
    # Illumina and 454 Specific
    parser.add_argument('-csv', '--csv',            required=False,                         dest = "csvPath",
                                                        help = 'CSV file path. See README File')

    parser.add_argument('-archaea', '--archaea',    required=False,   action="store",       dest = "archaea",
                                                        help = 'Use for Archaea perfect overlap')

    parser.add_argument('-f', '--config_format',  required=False,   action="store",     dest = "config_file_type",
                                                 help = 'ini or csv')


    parser.add_argument("-ft", "--seq_file_type",     required=False,  action="store",  dest = "input_file_format",
                                                    help="Sequence file type: fasta, fastq or sff ")
    parser.add_argument("-fs", "--seq_file_suffix",     required=False,  action="store",dest = "input_file_suffix",
                                                    help="Sequence file suffix [optional] ")

    parser.add_argument('-cp', '--compressed',  required=True,   action="store",       dest = "compressed",
                                                 help = 'Make it "False" if illumina fastq files are not compressed with gzip')
    parser.add_argument('-do_perfect', '--do_perfect',  required=False,   action="store",       dest = "do_perfect",
                                                 help = '"True" if it is perfect overlap, "False" - if partial. For illumina fastq files')
    parser.add_argument('-lane_name', '--lane_name',  required=False,   action="store",       dest = "lane_name",
                                                 help = '"If more then one lane for the same run date we want to create additional directories. For illumina. Default - empty')
    parser.add_argument('-db_host', '--database_host',  required=False,   action="store",  dest = "database_host",
                                                 help = 'Database host')
    parser.add_argument('-db_name', '--database_name',  required=False,   action="store", dest = "database_name",
                                                 help = 'Database name')
    #
    # VAMPS Specific: all can be in the ini file
    #
    parser.add_argument("-site",  "--site",         required=False,  action="store",   dest = "site",
                                                        help="""database hostname: vamps or vampsdev
                                                        [default: vampsdev]""")
    parser.add_argument("-u", "--user",             required=False,  action="store",   dest = "user",
                                                        help="user name")
    parser.add_argument("-proj", "--project",          required=False,  action='store', dest = "project",
                                                        help="")
    parser.add_argument('-dset',"--dataset",           required=False,  action="store",   dest = "dataset",
                                                        help = '')
    parser.add_argument("-load", "--load_database", required=False,  action="store",   dest = "load_db",
                                                        help = 'VAMPS: load files into vamps db')
    parser.add_argument("-env", "--envsource",      required=False,  action="store",   dest = "env_source_id",
                                                        help = '')
    parser.add_argument("-uc", "--use_cluster",      required=False,  action="store",   dest = "use_cluster",
                                                        help = '')
    parser.add_argument("-fasta","--fasta",                  required=False,  action="store",   dest = "fasta_file",
                                                        help = '')

    """
    TODO: not use, remove!
         # see note for base_output_dir in runconfig.py  about line: 130
    parser.add_argument("-o", "--baseoutputdir",     required=False,  action="store",   dest = "baseoutputdir",
                                                help="default: ./")
    """

    #DEBUG	Detailed information, typically of interest only when diagnosing problems.
    #INFO	Confirmation that things are working as expected.
    #WARNING	An indication that something unexpected happened, or indicative of some problem in the near future (e.g. 'disk space low').
    #           The software is still working as expected.
    #ERROR	Due to a more serious problem, the software has not been able to perform some function.
    #CRITICAL	A serious error, indicating that the program itself may be unable to continue running.

    args = parser.parse_args()


    requested_steps = args.steps.split(",")
    for step in requested_steps:
        if step not in C.existing_steps:
            print("\nInvalid processing step: " + step)
            print("Valid steps: ",', '.join(C.existing_steps),"\n")
            print("Exiting")
            sys.exit()

    if args.platform not in C.known_platforms:
    	sys.exit("unknown platform - Exiting")
    	
    v = MetadataUtils(command_line_args = args)

    # this will read the args and ini file and return a dictionary

    data_object = v.validate_args()
#    for attr in dir(data_object):
#        print("obj.%s = %s" % (attr, getattr(data_object, attr)))



    # set logging


    print("\nLog Level set to:", args.loglevel)
    logger.setLevel(args.loglevel.upper() )

    logger.info("Starting pipeline")
    ##############
    #
    #  Test cl parameters
    #
    ##############
    # CL RULES:
    # for ini file:  (no plurals)
    # 1) CL: input_dir ONLY shall be supplied on CL - no input filenames
    #
    # 2) All input files should be in the same directory AND of the same format
    #
    # 3) Supply a input_file_suffix on the CL if there are varying file types in the
    #       input_dir and you only are using some (default will read all files)
    # 4)
    #



    ##############
    #
    # CREATE or FIND OUTPUT DIRECTORY
    # need to look for or create output_dir here
    # base output directory and run are required so need to create output_dir here
    # to write ini file and status file
    ##############

#    try:
#        outdir = os.path.join(data_object['baseoutputdir'], data_object['run'])
#        #outdir = data_object['output_dir']
#        if not os.path.exists(outdir):
#            logger.debug("Creating output directory: "+outdir)
#            os.makedirs(outdir)
#    except:
#        sys.exit("Could not find or create the output_dir "+data_object['output_dir']+" - Exiting.")
#    data_object['output_dir'] = outdir
    is_user_upload = False #we never call pipeline-ui.py to do vamps user upload.
    dirs = Dirs(is_user_upload, data_object['run'], data_object['platform'], data_object['lane_name'])
    dirs.check_and_make_output_dir()
    dirs.create_all_output_dirs()
    data_object['output_dir'] = dirs.output_dir

    ##############
    #
    #  VALIDATE THE INI FILE
    #
    ##############


#    print('do1',data_object)
    del v
    v = MetadataUtils( configuration_dictionary = data_object )
    v.convert_and_save_ini(data_object['output_dir'])

    data_object = v.validate(data_object['output_dir'])
    #general_data = v.get_general_data()

    answer = v.get_confirmation(args.steps, data_object['general'])
    #print('do2',data_object)
    if answer == 'q':
        sys.exit()
    elif answer == 'v':
        # view CONFIG file contents
        fh = open(os.path.join(dirs.analysis_dir,  data_object['general']['run']+'.ini'))
        lines = fh.readlines()
        logger.debug("\n=== START ===\n")
        for line in lines:
            line = line.strip()
            logger.debug("line in INI: ")
            logger.debug(line)
        logger.debug("==== END ====\n")
        sys.exit()
    elif answer != 'c':
        sys.exit()
    ##############
    #
    # CREATE THE RUN OBJECT (see runconfig.py for details)
    #
    ##############
    runobj = Run(data_object, os.path.dirname(os.path.realpath(__file__)))


#    for key in run.samples:
#        print(key,run.samples[key].dataset)
#    sys.exit()
    ##############
    #
    # now do all the work
    #
    ##############
    process(runobj, args.steps)

