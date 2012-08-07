#!/usr/bin/env python

##!/usr/local/www/vamps/software/python/bin/python

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
sys.path.append("/bioware/pythonmodules/illumina-utils/")
sys.path.append("/Users/ashipunova/bin/illumina-utils")

import shutil
import types
from time import sleep, time, gmtime, strftime
from pipeline.utils import *
from pipeline.sample import Sample
from pipeline.runconfig import RunConfig
from pipeline.run import Run
from pipeline.chimera import Chimera
from pipeline.gast import Gast
from pipeline.vamps import Vamps
from pipeline.pipelinelogging import logger
from pipeline.trim_run import TrimRun
from pipeline.get_ini import readCSV
from pipeline.metadata import MetadataUtils
from pipeline.illumina_files import IlluminaFiles
from inspect import currentframe, getframeinfo

import logging
import json    
import fastalib as u
from pipeline.fasta_mbl_pipeline import MBLPipelineFastaUtils
from pipeline.db_upload import MyConnection, dbUpload 


# the main loop for performing each of the user's supplied steps
def process(run, steps):
    
    requested_steps = steps.split(",")            
    if 'clean' in requested_steps and len(requested_steps) > 1:
        sys.exit("The clean step cannot be combined with other steps - Exiting")
    
    # create output directory:
    # this should have been created in pipeline-ui.py. but just in case....
    if not os.path.exists(run.output_dir):
        logger.debug("Creating output directory: "+run.output_dir)
        os.makedirs(run.output_dir)  

    
    # Open run STATUS File here.
    # open in append mode because we may start the run in the middle
    # say at the gast stage and don't want to over write.
    # if we re-run trimming we'll get two trim status reports
    run.run_status_file_h = open(run.run_status_file_name, "a")
    
    # loop through official list...this way we execute the
    # users requested steps in the correct order 

    for step in C.existing_steps:
        if step in requested_steps:
            # call the method in here
            step_method = globals()[step]
            step_method(run)

def validate(run):
    #open_zipped_directory(run.run_date, run.output_dir)
    #logger.debug("Validating")
    pass
    #v = MetadataUtils(run, validate=True)
    
    #print 'Validates:  Configfile and Run Object'
    #run.run_status_file_h.write(strftime("%Y-%m-%d %H:%M:%S", gmtime())+"\tConfigFile Validated\n")

    

##########################################################################################
# perform trim step
# TrimRun.trimrun() does all the work of looping over each input file and sequence in each file
# all the stats are kept in the trimrun object
#
# when complete...write out the datafiles for the most part on a lane/runkey basis
#
def trim(run):
    # def is in utils.py
    #open_zipped_directory(run.run_date, run.output_dir)
    # (re) create the trim status file
    run.trim_status_file_h = open(run.trim_status_file_name, "w")
    
    # do the trim work
    mytrim = TrimRun(run) 
    
    # pass True to write out the straight fasta file of all trimmed non-deleted seqs
    # Remember: this is before chimera checking
    if run.platform == 'illumina':
        trim_codes = mytrim.trimrun_illumina(True)
    elif run.platform == '454':
        trim_codes = mytrim.trimrun_454(True)
    elif run.platform == 'ion-torrent':
        trim_codes = mytrim.trimrun_ion_torrent(True)
    else:
        trim_codes = ['ERROR','No Platform Found']
        
    trim_results_dict = {}
    if trim_codes[0] == 'SUCCESS':
        # setup to write the status
        new_lane_keys = trim_codes[2]
        trim_results_dict['status'] = "success"
        trim_results_dict['new_lane_keys'] = new_lane_keys
        logger.debug("Trimming finished successfully")
        # write the data files
        mytrim.write_data_files(new_lane_keys)
        run.trim_status_file_h.write(json.dumps(trim_results_dict))
        run.trim_status_file_h.close()
        run.run_status_file_h.write(json.dumps(trim_results_dict)+"\n")
        run.run_status_file_h.close()
    else:
        logger.debug("Trimming finished ERROR")
        trim_results_dict['status'] = "error"
        trim_results_dict['code1'] = trim_codes[1]
        trim_results_dict['code2'] = trim_codes[2]
        run.trim_status_file_h.write(json.dumps(trim_results_dict))
        run.trim_status_file_h.close()
        run.run_status_file_h.write(json.dumps(trim_results_dict)+"\n")
        run.run_status_file_h.close()
        sys.exit("Trim Error")
        
        
    # def is in utils.py: truncates and rewrites
    #zip_up_directory(run.run_date, run.output_dir, 'w')

# chimera assumes that a trim has been run and that there are files
# sitting around that describe the results of each lane:runkey sequences
# it also expectes there to be a trim_status.txt file around
# which should have a json format with status and the run keys listed        
def chimera(run):
    chimera_cluster_ids = [] 
    logger.debug("Starting Chimera Checker")
    # lets read the trim status file out here and keep those details out of the Chimera code
    idx_keys = get_keys(run)
    #new_lane_keys = convert_unicode_dictionary_to_str(json.loads(open(run.trim_status_file_name,"r").read()))["new_lane_keys"]
    
    mychimera = Chimera(run)
    
    c_den    = mychimera.chimera_denovo(idx_keys)
    if c_den[0] == 'SUCCESS':
        chimera_cluster_ids += c_den[2]
        chimera_code='PASS'
    elif c_den[0] == 'NOREGION':
        chimera_code='NOREGION'
    elif c_den[0] == 'FAIL':
        chimera_code = 'FAIL'
    else:
        chimera_code='FAIL'
    
    c_ref    = mychimera.chimera_reference(idx_keys)
    
    if c_ref[0] == 'SUCCESS':
        chimera_cluster_ids += c_ref[2]
        chimera_code='PASS'
    elif c_ref[0] == 'NOREGION':
        chimera_code = 'NOREGION'
    elif c_ref[0] == 'FAIL':
        chimera_code='FAIL'
    else:
        chimera_code='FAIL'
    
    #print chimera_cluster_ids
    run.chimera_status_file_h = open(run.chimera_status_file_name,"w")
    if chimera_code == 'PASS':  
        
        chimera_cluster_code = wait_for_cluster_to_finish(chimera_cluster_ids) 
        if chimera_cluster_code[0] == 'SUCCESS':
            logger.info("Chimera checking finished successfully")
            run.chimera_status_file_h.write("CHIMERA SUCCESS\n")
            run.run_status_file_h.write("CHIMERA SUCCESS\n")
            
        else:
            logger.info("3-Chimera checking Failed")
            run.chimera_status_file_h.write("3-CHIMERA ERROR: "+str(chimera_cluster_code[1])+" "+str(chimera_cluster_code[2])+"\n")
            run.run_status_file_h.write("3-CHIMERA ERROR: "+str(chimera_cluster_code[1])+" "+str(chimera_cluster_code[2])+"\n")
            sys.exit("3-Chimera checking Failed")
            
    elif chimera_code == 'NOREGION':
        logger.info("No regions found that need chimera checking")
        run.chimera_status_file_h.write("CHIMERA CHECK NOT NEEDED\n")
        run.run_status_file_h.write("CHIMERA CHECK NOT NEEDED\n")
        
    elif chimera_code == 'FAIL':
        logger.info("1-Chimera checking Failed")
        run.chimera_status_file_h.write("1-CHIMERA ERROR: \n")
        run.run_status_file_h.write("1-CHIMERA ERROR: \n")
        sys.exit("1-Chimera Failed")
    else:
        logger.info("2-Chimera checking Failed")
        run.chimera_status_file_h.write("2-CHIMERA ERROR: \n")
        run.run_status_file_h.write("2-CHIMERA ERROR: \n")
        sys.exit("2-Chimera checking Failed")
    sleep(2)   
    if  chimera_code == 'PASS' and  chimera_cluster_code[0] == 'SUCCESS':
        mychimera.write_chimeras_to_deleted_file(idx_keys)
        # should also recreate fasta
        # then read chimera files and place (or replace) any chimeric read_id
        # into the deleted file.
        
        mymblutils = MBLPipelineFastaUtils(idx_keys, mychimera.outdir)
        
        # write new cleaned files that remove chimera if apropriate
        # these are in fasta_mbl_pipeline.py
        # the cleaned file are renamed to the original name:
        # lane_key.unique.fa
        # lane_key.trimmed.fa
        # lane_key.names        -- 
        # lane_key.abund.fa     -- this file is for the uclust chimera script
        # lane_key.deleted.txt  -- no change in this file
        # THE ORDER IS IMPORTANT HERE:
        mymblutils.write_clean_fasta_file()
        mymblutils.write_clean_names_file()
        mymblutils.write_clean_uniques_file()
        mymblutils.write_clean_abundance_file()
        # write keys file for each lane_key - same fields as db table? for easy writing
        # write primers file for each lane_key
 
        
        # Write new clean files to the database
        # rawseq table not used
        # trimseq
        # runkeys
        # primers
        # run primers
        mymblutils.write_clean_files_to_database()
        
    # def is in utils.py: appends
    #zip_up_directory(run.run_date, run.output_dir, 'a')
def illumina_files(run):  
    start = time()
#    if os.uname()[1] == 'ashipunova.mbl.edu':
#        import shutil 
#        shutil.rmtree('/Users/ashipunova/BPC/py_mbl_sequencing_pipeline/test/data/fastq/illumina_files_test/output/analysis/')
    illumina_files = IlluminaFiles(run)
    illumina_files.split_files(compressed = run.compressed)
    illumina_files.perfect_reads()
    illumina_files.uniq_fa()
    
    elapsed = (time() - start)
    print "illumina_files time = %s" % str(elapsed)
        
def env454run_info_upload(run):

    my_read_csv = dbUpload(run)
    start = time()
    my_read_csv.put_run_info()
    elapsed = (time() - start)
    print "put_run_info time = %s" % str(elapsed)
    
def env454upload(run):  
    """
    Run: pipeline dbUpload testing -c test/data/JJH_KCK_EQP_Bv6v4.ini -s env454upload -l debug
    For now upload only Illumina data to env454 from files, assuming that all run info is already on env454 (run, run_key, dataset, project, run_info_ill tables) 
    TODO: 
        2) Upload env454 data into raw, trim, gast etc tables from files
    """
    
    whole_start = time()

#    my_read_csv = readCSV(run)
#    my_read_csv.read_csv()
    
    my_env454upload = dbUpload(run)
    filenames   = my_env454upload.get_fasta_file_names()
    seq_in_file = 0
    total_seq   = 0
    
    for filename in filenames:
        try:
            logger.debug("\n----------------\nfilename = %s" % filename)
            fasta_file_path = filename
            filename_base   = "-".join(filename.split("/")[-1].split("-")[:-1])
            run_info_ill_id = my_env454upload.get_run_info_ill_id(filename_base)
            gast_dict       = my_env454upload.get_gasta_result(filename)
            read_fasta      = u.ReadFasta(fasta_file_path)
            sequences       = read_fasta.sequences
            if not (len(sequences)):
                continue            
            read_fasta.close()
            fasta           = u.SequenceSource(fasta_file_path, lazy_init = False) 

            insert_seq_time      = 0   
            get_seq_id_dict_time = 0
            insert_pdr_info_time = 0
            insert_taxonomy_time = 0
            insert_sequence_uniq_info_ill_time = 0
            
            start = time()

            my_env454upload.insert_seq(sequences)
            elapsed = (time() - start)
            insert_seq_time = elapsed
            logger.debug("seq_in_file = %s" % seq_in_file)
            logger.debug("insert_seq() took %s time to finish" % insert_seq_time)
#            print "insert_seq() took ", elapsed, " time to finish"
            start = time()
            my_env454upload.get_seq_id_dict(sequences)
            elapsed = (time() - start)
            get_seq_id_dict_time = elapsed
            logger.debug("get_seq_id_dict() took %s time to finish" % get_seq_id_dict_time)
            
            while fasta.next():
#                sequence_ill_id = my_env454upload.get_sequence_id(fasta.seq)
                start = time()
#                print "Inserting pdr info"
                my_env454upload.insert_pdr_info(fasta, run_info_ill_id)
                elapsed = (time() - start)
                insert_pdr_info_time += elapsed
#                print "insert_pdr_info() took ", elapsed, " time to finish"                

                start = time()
#                print "Inserting taxonomy"
                my_env454upload.insert_taxonomy(fasta, gast_dict)

                elapsed = (time() - start)
                insert_taxonomy_time += elapsed

#                print "tax_id = ", tax_id ,"; insert_taxonomy() took ", elapsed, " time to finish"                
#                print "tax_id = ", tax_id            

                start = time()
#                print "Inserting sequence_uniq_info_ill"
                my_env454upload.insert_sequence_uniq_info_ill(fasta, gast_dict)
                elapsed = (time() - start)
                insert_sequence_uniq_info_ill_time += elapsed

            seq_in_file = fasta.total_seq
            my_env454upload.put_seq_statistics_in_file(filename, fasta.total_seq)
            total_seq += seq_in_file
            logger.debug("insert_pdr_info() took %s time to finish" % insert_pdr_info_time)
            logger.debug("insert_taxonomy_time() took %s time to finish" % insert_taxonomy_time)
            logger.debug("insert_sequence_uniq_info_ill() took %s time to finish" % insert_sequence_uniq_info_ill_time)

            
#        except Exception, e:          # catch all deriving from Exception (instance e)
##            sys.stderr.write('\r[fastalib] Reading FASTA into memory: %s' % (self.fasta.pos))
#            frameinfo = getframeinfo(currentframe())
#            print frameinfo.filename, frameinfo.lineno
#            print "\r[pipelineprocessor] Exception: ", e.__str__()      # address the instance, print e.__str__()
##            raise                       # re-throw caught exception   
        except:                       # catch everything
            print "\r[pipelineprocessor] Unexpected:"         # handle unexpected exceptions
            print sys.exc_info()[0]     # info about curr exception (type,value,traceback)
            raise                       # re-throw caught exception   
#    print "total_seq = %s" % total_seq
    my_env454upload.check_seq_upload()
    logger.debug("total_seq = %s" % total_seq)
    whole_elapsed = (time() - whole_start)
    print "The whole_upload took %s s" % whole_elapsed
    
    # for vamps 'new_lane_keys' will be prefix 
    # of the uniques and names file
    # that was just created in vamps_gast.py
#    if(run.vamps_user_upload):
#        lane_keys = [run.user+run.runcode]        
#    else:
#        lane_keys = convert_unicode_dictionary_to_str(json.loads(open(run.trim_status_file_name,"r").read()))["new_lane_keys"]
    
#    print "PPP anchors = %s, base_output_dir = %s, base_python_dir = %s, chimera_status_file_h = %s, chimera_status_file_name = %s,\n\
#     force_runkey = %s, gast_input_source = %s, initializeFromDictionary = %s, input_dir = %s, input_file_info = %s, maximumLength = %s,\n\
#      minAvgQual = %s, minimumLength = %s, output_dir = %s, platform = %s, primer_suites = %s, require_distal = %s, run_date = %s, \n\
#      run_key_lane_dict = %s, run_keys = %s, samples = %s, sff_files = %s, trim_status_file_h = %s, trim_status_file_name = %s, vamps_user_upload = %s\n" % (run.anchors, run.base_output_dir, run.base_python_dir, run.chimera_status_file_h, run.chimera_status_file_name, run.force_runkey, run.gast_input_source, run.initializeFromDictionary, run.input_dir, run.input_file_info, run.maximumLength, run.minAvgQual, run.minimumLength, run.output_dir, run.platform, run.primer_suites, run.require_distal, run.run_date, run.run_key_lane_dict, run.run_keys, run.samples, run.sff_files, run.trim_status_file_h, run.trim_status_file_name, run.vamps_user_upload)
#   dir(run) = ['__doc__', '__init__', '__module__', 'anchors', 'base_output_dir', 'base_python_dir', 'chimera_status_file_h', 
#'chimera_status_file_name', 'force_runkey', 'gast_input_source', 'initializeFromDictionary', 'input_dir', 'input_file_info', 'maximumLength', 
#'minAvgQual', 'minimumLength', 'output_dir', 'platform', 'primer_suites', 'require_distal', 'run_date', 'run_key_lane_dict', 'run_keys', 'samples', 
#'sff_files', 'trim_status_file_h', 'trim_status_file_name', 'vamps_user_upload']

#    logger.debug("PPP run.rundate = ")
#    logger.debug(run.rundate)
#    my_env454upload.select_run(lane_keys)


def gast(run):  
    
    
    # for vamps 'new_lane_keys' will be prefix 
    # of the uniques and names file
    # that was just created in vamps_gast.py
    # or we can get the 'lane_keys' directly from the config_file
    # for illumina:
    # a unique idx_key is a concatenation of barcode_index and run_key
    # Should return a list not a string
    idx_keys = get_keys(run)
    
    # get GAST object
    mygast = Gast(run, idx_keys)
    
    
    # Check for unique files and create them if not there
    result_code = mygast.check_for_uniques_files(idx_keys)
    run.run_status_file_h.write(json.dumps(result_code)+"\n")
    if result_code[0] == 'ERROR':
        logger.error("uniques not found failed")
        sys.exit("uniques not found failed")
    sleep(5)
    
    # CLUSTERGAST
    result_code = mygast.clustergast()
    run.run_status_file_h.write(json.dumps(result_code)+"\n")
    if result_code[0] == 'ERROR':
        logger.error("clutergast failed")
        sys.exit("clustergast failed")
    sleep(5)
    
    # GAST_CLEANUP
    result_code = mygast.gast_cleanup()
    run.run_status_file_h.write(json.dumps(result_code)+"\n")
    if result_code[0] == 'ERROR':
        logger.error("gast_cleanup failed")        
        sys.exit("gast_cleanup failed")
    sleep(5)
    
    # GAST2TAX
    result_code = mygast.gast2tax()
    run.run_status_file_h.write(json.dumps(result_code)+"\n")
    if result_code[0] == 'ERROR':
        logger.error("gast2tax failed") 
        sys.exit("gast2tax failed")
        
def cluster(run):
    """
    TO be developed eventually:
        Select otu creation method
        using original trimmed sequences
    """
    pass
    
    
    
def vampsupload(run):
    """
    Upload data files to VAMPS database
    """
    # for vamps 'new_lane_keys' will be prefix 
    # of the uniques and names file
    # that was just created in vamps_gast.py
    # or we can get the 'lane_keys' directly from the config_file
    # for illumina:
    # a unique idx_key is a concatenation of barcode_index and run_key
    idx_keys = get_keys(run)

#     if(run.vamps_user_upload):
#         idx_keys = [run.user+run.runcode]        
#     else:
#         idx_keys = convert_unicode_dictionary_to_str(json.loads(open(run.trim_status_file_name,"r").read()))["new_lane_keys"]
                
    myvamps = Vamps(run)
    
        
    myvamps.taxonomy(idx_keys)
    myvamps.sequences(idx_keys)        
    myvamps.exports(idx_keys)
    myvamps.projects(idx_keys)
    myvamps.info(idx_keys)
    #myvamps.load_database(idx_keys)
def status(run):
    
    f = open(run.run_status_file_name)
    lines = f.readlines()
    f.close()
    
    print "="*40
    print "STATUS LOG: "
    for line in lines:
        line =line.strip()
        print line
    print "="*40+"\n"
    
def clean(run):
    """
    Removes a run from the database and output directory
    """
    
    answer = raw_input("\npress 'y' to delete the run '"+run.run_date+"': ")
    if answer == 'y' or answer == 'Y':
        
        for (archiveDirPath, dirNames, fileNames) in os.walk(run.output_dir):
            print "Removing run:",run.run_date
            for file in fileNames:
                filePath = os.path.join(run.output_dir,file)
                print filePath
                os.remove(os.path.join(run.output_dir,file))
                # should we also remove STATUS.txt and *.ini and start again?
                # the directory will remain with an empty STATUS.txt file
                #os.removedirs(run.output_dir)

def get_keys(run):
    try:
        idx_keys = convert_unicode_dictionary_to_str(json.loads(open(run.trim_status_file_name,"r").read()))["new_lane_keys"]
        # {"status": "success", "new_lane_keys": ["1_GATGA"]}
    except:
        # here we have no idx_keys - must create them from run
        # if illumina they are index_runkey_lane concatenation
        # if 454 the are lane_key
        if run.platform == 'illumina':  
            idx_keys = run.idx_keys
            ct = 0
            for h in run.samples:
                logger.debug(h,run.samples[h])
                ct +=1
            print ct
        elif run.platform == '454':
            idx_keys = run.idx_keys
        elif run.platform == 'ion_torrent':
            idx_keys = run.idx_keys
        elif run.platform == 'vamps':
            idx_keys = [run.user+run.run]  
        else:
            logger.debug("GAST: No keys found - Exiting")
            run.run_status_file_h.write("GAST: No keys found - Exiting\n")
            sys.exit()
    if type(idx_keys) is types.StringType:
        return idx_keys.split(',')
    elif type(idx_keys) is types.ListType:
        return idx_keys
    else:
        return None
    return idx_keys