import subprocess
import sys, os, stat
import time
import shutil

#import logging
import constants as C
import re
import json
from types import *



class Gast:
    """The Gast class takes a uniqued fasta file for each dataset (vamps), or lane_key (illumina)
        clustergast: clusterizing, gast
        gast_cleanup: expand the results onto duplicate names; collect refhvr_ids for each read_id
        gast2tax:

    """
    Name = "GAST"
    def __init__(self, run_object = None, idx_keys=[]):
        self.runobj = run_object
        if self.runobj.site == 'vamps' or self.runobj.site == 'vampsdev' or self.runobj.site == 'new_vamps':
            sys.path.append('/groups/vampsweb/py_mbl_sequencing_pipeline')
        else:
            sys.path.append('/bioware/linux/seqinfo/bin/python_pipeline/py_mbl_sequencing_pipeline')

        from pipeline.pipelinelogging import logger
        from pipeline.utils import Dirs, PipelneUtils
        self.logger = logger
        self.test   = True
        self.utils  = PipelneUtils()

        print('SITE', self.runobj.site)
        self.use_cluster = self.runobj.use_cluster
        if self.runobj.vamps_user_upload:
            self.idx_keys  = [self.runobj.user+self.runobj.run]
            self.refdb_dir = C.vamps_ref_database_dir
            self.iterator  = self.runobj.datasets
            site = self.runobj.site
            if site == 'new_vamps':  # vampsdev and vamps and new_vamps NOT local installation
                dir_prefix = self.runobj.project_dir
            else:
                dir_prefix = self.runobj.user+'_'+self.runobj.run
        else:
            self.idx_keys  = idx_keys
            self.iterator  = self.idx_keys
            self.refdb_dir = C.ref_database_dir
            site = ''
            dir_prefix = self.runobj.run



            if self.utils.is_local():
                self.refdb_dir = C.ref_database_dir_local

        dirs = Dirs(self.runobj.vamps_user_upload, dir_prefix, self.runobj.platform, site = site)
#
#        self.out_file_path = dirs.check_dir(dirs.analysis_dir)
#        self.results_path  = dirs.check_dir(dirs.reads_overlap_dir)
        self.reads_dir = dirs.check_dir(dirs.reads_overlap_dir)


#
##                program_name = "/Users/ashipunova/bin/illumina-utils/analyze-illumina-v6-overlaps"
#                self.refdb_dir = "/Users/ashipunova/bin/illumina-utils/"

        #"For VAMPS-user-uload:"
        #os.environ['SGE_ROOT'] ='/opt/sge'
        #os.environ['SGE_CELL'] ='grendel'
        #path                   = os.environ['PATH']
        #os.environ['PATH']     = '/usr/local/sge/bin/lx24-amd64:'+path

        # limiting datasets for testing
        self.limit = 400

        # If we are here from a vamps gast process
        # then there should be just one dataset to gast <- NOT TRUE
        # but if MBL/illumina pipe then many datasets are probably involved.

        self.analysis_dir = dirs.check_dir(dirs.analysis_dir)

        self.global_gast_dir = dirs.check_dir(dirs.gast_dir)

        # create our directories for each key

        dirs.create_gast_name_dirs(self.iterator)
        # determin which database type will be in uclust command
        self.db_type='udb'


    def clustergast(self):
        """
        clustergast - runs the GAST pipeline on the cluster.
               GAST uses UClust to identify the best matches of a read sequence
               to references sequences in a reference database.
               VAMPS: The uniques and names files have previously been created in trim_run.py.
               Illumina: The uniques and names files have been created by illumina_files.py
        """
        self.logger.info("Starting Clustergast")

        self.runobj.run_status_file_h.write(json.dumps({'status':'STARTING_CLUSTERGAST'})+"\n")
        # Step1: create empty gast table in database: gast_<rundate>
        # Step2: Count the number of sequences so the job can be split for nodes
        # $facount = `grep -c \">\" $fasta_uniqs_filename`;
        # $calcs = `/bioware/seqinfo/bin/calcnodes -t $facount -n $nodes -f 1`;

        #   /bioware/seqinfo/bin/fastasampler -n $start, $end ${gastDir}/${fasta_uniqs_filename} $tmp_fasta_filename
        #   $usearch_binary --global --query $tmp_fasta_filename --iddef 3 --gapopen 6I/1E --db $refhvr_fa --uc $tmp_usearch_filename --maxaccepts $max_accepts --maxrejects $max_rejects --id $pctid_threshold
        #   # sort the results for valid hits, saving only the ids and pct identity
        #   grep -P \"^H\\t\" $tmp_usearch_filename | sed -e 's/|.*\$//' | awk '{print \$9 \"\\t\" \$4 \"\\t\" \$10 \"\\t\" \$8}' | sort -k1,1b -k2,2gr | clustergast_tophit > $gast_filename
        #   Submit the script
        #   /usr/local/sge/bin/lx24-amd64/qsub $qsub_priority $script_filename

        calcnodes = C.calcnodes_cmd
        if self.utils.is_local():
            calcnodes = C.calcnodes_cmd_local
            clusterize = C.clusterize_cmd
        elif self.utils.is_vamps():   # new vamps
            calcnodes = C.calcnodes_cmd_vamps
            clusterize = C.clusterize_cmd_vamps
        elif self.runobj.site == 'vamps' or self.runobj.site == 'vampsdev' or self.runobj.site == 'new_vamps':
            calcnodes = C.calcnodes_cmd_vamps
            clusterize = C.clusterize_cmd_vamps
        else:
            calcnodes = C.calcnodes_cmd
            clusterize = C.clusterize_cmd
#        sqlImportCommand = C.mysqlimport_cmd
#        if self.utils.is_local():
#            sqlImportCommand = C.mysqlimport_cmd_local

        #qsub = '/usr/local/sge/bin/lx24-amd64/qsub'


        ###################################################################
        # use fasta.uniques file
        # split into smaller files
        # usearch --cluster each
        #######################################
        #
        # Split the uniques fasta and run UClust per node
        #
        #######################################
        qsub_prefix = 'clustergast_sub_'
        gast_prefix = 'gast_'
        if self.use_cluster:
            self.logger.info("Using cluster for clustergast")
        else:
            self.logger.info("Not using cluster")


        key_counter    = 0
        gast_file_list = []
        qsub_id_list=[]
        num_keys = len(self.iterator)
        cluster_nodes  = C.cluster_nodes
        self.logger.info("xCluster nodes set to: "+str(cluster_nodes))
        for key in self.iterator:
            key_counter += 1
            print("\nDirectory", str(key_counter), key)
            print('use_cluster:', self.use_cluster)
            if self.runobj.vamps_user_upload:
                output_dir  = os.path.join(self.global_gast_dir, key)
                gast_dir    = os.path.join(self.global_gast_dir, key)
                if self.runobj.platform == 'illumina':

                    # use same file
                    fasta_file = os.path.join(output_dir, 'unique.fa')
                    unique_file = os.path.join(output_dir, 'unique.fa')
                else:
                    fasta_file = os.path.join(output_dir, 'fasta.fa')
                    unique_file = os.path.join(output_dir, 'unique.fa')
                names_file  = os.path.join(output_dir, 'names')
                #datasets_file = os.path.join(self.global_gast_dir, 'datasets')
                #print('gast_dir:', gast_dir)
                print('unique_file:', unique_file)
            else:
                if self.runobj.platform == 'illumina':
                    output_dir  = os.path.join(self.global_gast_dir, key)
                    gast_dir    = os.path.join(self.global_gast_dir, key)
                    file_prefix = key
#                    file_prefix = self.runobj.samples[key].file_prefix
                    unique_file = os.path.join(self.reads_dir, file_prefix + "-PERFECT_reads.fa.unique")
                    names_file  = os.path.join(self.reads_dir, file_prefix + "-PERFECT_reads.fa.unique.names")
                elif self.runobj.platform == '454':
                    pass
                else:
                    sys.exit("clustergast: no platform")

            if key_counter >= self.limit:
                pass

            #print('samples', key, self.runobj.samples)
            if key in self.runobj.samples:
                dna_region = self.runobj.samples[key].dna_region
            else:
                dna_region = self.runobj.dna_region
            if not dna_region:
                self.logger.error("clustergast: We have no DNA Region: Setting dna_region to 'unknown'")
                dna_region = 'unknown'

            (refdb, taxdb) = self.get_reference_databases(dna_region)
#            if self.runobj.use_full_length == True:
#             #if self.runobj.project[:3] == 'MBE':
#                 # for some reason usearch64 doeasnt like the .udb file
#                 refdb = '/groups/vampsweb/blastdbs/refssu.wdb'
#                 taxdb = '/groups/vampsweb/blastdbs/refssu.tax'
#                 self.db_type='wdb'
#
#             if self.runobj.use_full_length == True:
#             #if self.runobj.project[:3] == 'MBE':
#                 #use_64bit_usearch = True
#                 # for some reason usearch64 doeasnt like the .udb file
#                 refdb = '/groups/vampsweb/blastdbs/refssu.wdb'
#                 taxdb = '/groups/vampsweb/blastdbs/refssu.tax'
#                 self.db_type='wdb'


            if os.path.exists(unique_file) and (os.path.getsize(unique_file) > 0):
                print("cluster nodes: "+str(cluster_nodes))
                i = 0
                if cluster_nodes:
                    grep_cmd = ['grep', '-c', '>', unique_file]
                    self.logger.debug( ' '.join(grep_cmd) )
                    facount = subprocess.check_output(grep_cmd).strip()
                    self.logger.debug('From gast.py, if cluster_nodes' + key + ' count ' + facount)
                    calcnode_cmd = [calcnodes, '-t', str(facount), '-n', str(cluster_nodes), '-f', '1']

                    calcout = subprocess.check_output(calcnode_cmd).strip()
                    #self.logger.debug("calcout:\n"+calcout)
                    self.logger.debug("facount: "+str(facount)+"\n")
                    #calcout:
                    # node=1 start=1 end=1 rows=1
                    # node=2 start=2 end=2 rows=1
                    # node=3 start=3 end=3 rows=1
                    lines = calcout.split("\n")
                    #gast_file_list = []
                    'Create empty files'

                    for line in lines:
                        i += 1
                        self.logger.debug("\n\n>>>>>>>>> Count: "+str(i)+'/'+str(cluster_nodes)+ " -- Dataset Count:"+str(key_counter)+'/'+str(num_keys))
                        if i >= cluster_nodes:
                            continue
                        script_filename      = os.path.join(gast_dir, qsub_prefix + str(i))
                        gast_filename        = os.path.join(gast_dir, gast_prefix + str(i))
                        fastasamp_filename   = os.path.join(gast_dir, 'samp_' + str(i))
                        "!!! output = 100"
                        clustergast_filename = os.path.join(gast_dir, key+".gast_" + str(i))
                        gast_file_list.append(clustergast_filename)
                        usearch_filename     = os.path.join(gast_dir, "uc_" + str(i))
                        log_file             = os.path.join(gast_dir, 'clustergast.log_' + str(i))

                        data = line.split()

                        if len(data) < 2:
                            continue
                        start = data[1].split('=')[1]
                        end  = data[2].split('=')[1]

                        'creating sctipts to run on grendel'
                        if self.use_cluster:
                            fh = open(script_filename, 'w')
                            qstat_name = "gast" + key + '_' + self.runobj.run + "_" + str(i)
                            fh.write("#!/bin/sh\n\n")

                            # don't need these commands unless running qsub directly (w/o clusterize)
                            #fh.write("#$ -j y\n" )
                            #fh.write("#$ -o " + log_file + "\n")
                            #fh.write("#$ -N " + qstat_name + "\n\n")

                            # setup environment
                            'move to constants py'
                            fh.write("source /xraid/bioware/Modules/etc/profile.modules\n")
                            fh.write("module load bioware\n\n")

                        fs_cmd = self.get_fastasampler_cmd(unique_file, fastasamp_filename, start, end)


                        self.logger.debug("fastasampler command: "+fs_cmd)

                        if self.use_cluster:
                            fh.write(fs_cmd + "\n")
                        else:
                            subprocess.call(fs_cmd, shell=True)

                        us_cmd = self.get_usearch_cmd(fastasamp_filename, refdb, usearch_filename, self.runobj.use64bit)

                        self.logger.debug("vsearch command: "+us_cmd)

                        if self.use_cluster:
                            fh.write(us_cmd + "\n")
                        else:
                            subprocess.call(us_cmd, shell=True)

                        grep_cmd = self.get_grep_cmd(usearch_filename, clustergast_filename)

                        self.logger.debug("grep command: "+grep_cmd)
                        if self.use_cluster:
                            self.logger.debug("using grendel cluster for vsearch")
                            fh.write(grep_cmd + "\n")
                            fh.close()
                            # make script executable and run it
                            #print(script_filename)

                            #os.chmod(script_filename, stat.S_IRWXU)
                            subprocess.Popen('chmod +x '+script_filename, shell=True)
                            #qsub_cmd = clusterize + " " + script_filename
                            opts = " -n 8 "
                            #qsub_cmd = clusterize + " -log " + log_file + " -n 8 " + script_filename
                            qsub_cmd = clusterize + ' -log ' + log_file + ' '+  script_filename
                            # on vamps and vampsdev qsub cannot be run - unless you call it from the
                            # cluster aware directories /xraid2-2/vampsweb/vamps and /xraid2-2/vampsweb/vampsdev
                            #qsub_cmd = C.qsub_cmd + " " + script_filename
                            self.logger.debug("qsub command: "+qsub_cmd)
                            #print('qsub CMD:',qsub_cmd)
                            proc = subprocess.check_output(qsub_cmd, shell=True)
                            self.logger.debug('proc: '+proc)
                            #print('proc: ',proc)
                            try:
                                lines = proc.split("\n")
                                for line in lines:
                                    #print('LINE',line)
                                    items = line.split()
                                    if items[0] == 'Your' and items[1] == 'job':
                                        qsub_id = items[2]
                                # Your job 990889 ("clustergast_sub_46") has been submitted
                                        qsub_id_list.append(qsub_id)
                            except:
                                self.logger.debug('Could not split proc - Continuing on...')

                            # proc.communicate will block - probably not what we want
                            #(stdout, stderr) = proc.communicate() #block the last onehere
                            #print(stderr, stdout)
                            time.sleep(0.1)

                        else:
                            self.logger.debug("NOT using cluster for vsearch")
                            subprocess.call(grep_cmd, shell=True)
                            self.logger.debug("grep_cmd: ")
                            self.logger.debug(grep_cmd)

                else:
                    """works only if custer_nodes = 0 or False. In constants.py it's 100
                    Call this either from here or from 100 scripts we'll create
                    """
                    #fastasamp_filename = os.path.join(gast_dir, 'samp')
                    # no nodes means that just one file will be run by clusterize
                    usearch_filename= os.path.join(gast_dir, "uc")
                    clustergast_filename_single   = os.path.join(gast_dir, "gast"+dna_region)
                    gast_file_list = [clustergast_filename_single]
                    #print(usearch_filename, clustergast_filename_single)

                    us_cmd = self.get_usearch_cmd(unique_file, refdb, usearch_filename, self.runobj.use64bit)
                    #print(us_cmd)
                    subprocess.call(us_cmd, shell=True)
                    grep_cmd = self.get_grep_cmd(usearch_filename, clustergast_filename_single)
                    #print(grep_cmd)
                    subprocess.call(grep_cmd, shell=True)
            else:
                self.logger.warning( "unique_file not found or zero size: "+unique_file)


        if self.use_cluster:
            'check if clusters are done'
            # wait here for all the clustergast scripts to finish

            print("Checking cluster jobs")
            result = self.waiting_on_cluster( self.runobj.site, qsub_id_list )
            time.sleep(10)

            print('USEARCH: cluster jobs are complete')

        for key in self.iterator:

            if self.runobj.vamps_user_upload:
                gast_dir = os.path.join(self.global_gast_dir, key)
            else:
                if self.runobj.platform == 'illumina':
                    gast_dir = os.path.join(self.global_gast_dir, key)
                elif self.runobj.platform == '454':
                    pass
                else:
                    sys.exit("clustergast: no platform")

            # now concatenate all the clustergast_files into one file (if they were split)
            if cluster_nodes:
                # gast file

                clustergast_filename_single   = os.path.join(gast_dir, "gast"+dna_region)
                print("Concatenating ds.gast_x files into"+clustergast_filename_single)
                clustergast_fh = open(clustergast_filename_single, 'w')
                # have to turn off cluster above to be able to 'find' these files for concatenation
                for n in range(1, C.cluster_nodes-1):
                    #cmd = "cat "+ gast_dir + key+".gast_" + str(n) + " >> " + gast_dir + key+".gast"
                    file = os.path.join(gast_dir, key+".gast_" + str(n))
                    self.logger.info('ds.gast file:'+file)
                    if(os.path.exists(file)):
                        shutil.copyfileobj(open(file, 'rb'), clustergast_fh)
                    else:
                        self.logger.info( "Could not find file: "+os.path.basename(file)+" Skipping")

                clustergast_fh.flush()
                clustergast_fh.close()

        print("Finished clustergast")
        self.logger.info("Finished clustergast")
        #sys.exit()
        return {'status':"GAST_SUCCESS", 'message':"Clustergast Finished"}


    def gast_cleanup(self):
        """
        gast_cleanup - follows clustergast, explodes the data and copies to gast_concat and gast files
        """
        self.runobj.run_status_file_h.write(json.dumps({'status':'STARTING_GAST_CLEANUP'})+"\n")
        for key in self.iterator:
            "UTIL: Dirs: create file names"
            if self.runobj.vamps_user_upload:
                output_dir = os.path.join(self.global_gast_dir, key)
                gast_dir = os.path.join(self.global_gast_dir, key)
                if self.runobj.platform == 'illumina':
                    # use same file
                    fasta_file = os.path.join(output_dir, 'unique.fa')
                    unique_file = os.path.join(output_dir, 'unique.fa')
                else:
                    fasta_file = os.path.join(output_dir, 'fasta.fa')
                    unique_file = os.path.join(output_dir, 'unique.fa')
                names_file = os.path.join(output_dir, 'names')
                #datasets_file = os.path.join(self.global_gast_dir, 'datasets')
            else:
                if self.runobj.platform == 'illumina':
                    output_dir = os.path.join(self.global_gast_dir, key)
                    gast_dir = os.path.join(self.global_gast_dir, key)
                    file_prefix = self.runobj.samples[key].file_prefix
                    unique_file = os.path.join(self.input_dir, file_prefix+"-PERFECT_reads.fa.unique")
                    names_file = os.path.join(self.input_dir, file_prefix+"-PERFECT_reads.fa.unique.names")
                elif self.runobj.platform == '454':
                    pass
                else:
                    sys.exit("gast_cleanup: no platform")

            if key in self.runobj.samples:
                dna_region = self.runobj.samples[key].dna_region
            else:
                dna_region = self.runobj.dna_region
            if not dna_region:
                self.logger.error("gast_cleanup: We have no DNA Region: Setting dna_region to 'unknown'")
                self.runobj.run_status_file_h.write(json.dumps({'status':'WARNING', 'message':"gast_cleanup: We have no DNA Region: Setting dna_region to 'unknown'"})+"\n")
                dna_region = 'unknown'
            # find gast_dir

            'Check in Dirs'
            if not os.path.exists(gast_dir):
                self.logger.error("Could not find gast directory: "+gast_dir+" Exiting")
                sys.exit()

            'create in Dirs'
            clustergast_filename_single   = os.path.join(gast_dir, "gast"+dna_region)
            try:
                self.logger.debug('gast filesize:'+str(os.path.getsize(clustergast_filename_single)))
            except:
                self.logger.debug('gast filesize: zero')

            gast_filename          = os.path.join(gast_dir, "gast")
            gastconcat_filename    = os.path.join(gast_dir, "gast_concat")
            #dupes_filename    = os.path.join(gast_dir, "dupes")
            #nonhits_filename    = os.path.join(gast_dir, "nonhits")
            copies  = {}
            nonhits = {}
            # open and read names file

            'TODO: put here create names file for illumina'
            if os.path.exists(names_file) and os.path.getsize(names_file) > 0:
                names_fh = open(names_file, 'r')
                for line in names_fh:
                    s = line.strip().split("\t")

                    index_read = s[0]
                    if len(s) >1:
                        copies[index_read] = s[1].split(',')

                    if index_read in nonhits:
                        nonhits[index_read] += 1
                    else:
                        nonhits[index_read] = 1



                names_fh.close()
            #print(nonhits)
            #print(copies)

            #######################################
            #
            #  Insert records with valid gast hits into gast_file
            #
            #######################################
            # read the .gast file from clustergast
            concat = {}

            gast_fh     = open(gast_filename, 'w')
            if os.path.exists(clustergast_filename_single):
                in_gast_fh  = open(clustergast_filename_single, 'r')

                for line in in_gast_fh:

                    s = line.strip().split("\t")
                    if len(s) == 4:
                        read_id     = s[0]
                        refhvr_id   = s[1].split('|')[0]
                        distance    = s[2]
                        alignment   = s[3]
                        frequency   = 0
                    elif len(s) == 5:
                        read_id     = s[0]
                        refhvr_id   = s[1].split('|')[0]
                        distance    = s[2]
                        alignment   = s[3]
                        frequency   = s[4]
                    else:
                        self.logger.debug("gast_cleanup: wrong field count")
                    #print(read_id, refhvr_id)
                    # if this was in the gast table zero it out because it had a valid hit
                    # so we don't insert them as non-hits later
                    if read_id in nonhits:
                        del nonhits[read_id]
                        #print('deleling', read_id)
                    #print('nonhits', nonhits)
                    if read_id not in copies:
                        self.logger.info(read_id+' not in names copies: Skipping')
                        continue

                    # give the same ref and dist for each duplicate
                    for id in copies[read_id]:

                        if id != read_id:
                            #print(id, read_id, distance, refhvr_id)
                            gast_fh.write( id + "\t" + refhvr_id + "\t" + distance + "\t" + alignment +"\t"+frequency+"\n" )


                in_gast_fh.close()

                #######################################
                #
                #  Insert a record for any valid sequence that had no blast hit and therefore no gast result
                #       into gast_filename
                #
                #######################################
                for read in sorted(nonhits.iterkeys()):
                    if read in copies:
                        for d in copies[read]:
                            gast_fh.write( d+"\t0\t1\t0\t0\n")
                    else:
                        self.logger.info(read+' not in copies: Skipping')


                gast_fh.close()

                # concatenate the two gast files
                clustergast_fh = open(clustergast_filename_single, 'a')
                'add dupilicate info into original result  '
                shutil.copyfileobj(open(gast_filename, 'rb'), clustergast_fh)
                clustergast_fh.close()
                #then open again and get data for gast concat
                concat = {}
                #print(clustergast_filename_single)
                'create content for the gast_concat table'
                # M01925:91:000000000-A7PJY:1:1102:19152:21839	DQ874340_1_1390	0.007	264I151M975I	99
                for line in open(clustergast_filename_single, 'r'):
                    data = line.strip().split("\t")
                    id = data[0]
                    try:
                        refhvr_id = data[1].split('|')[0]
                    except:
                        refhvr_id = data[1]
                    distance = data[2]
                    #print('data', data)
                    if id in concat:
                        concat[id]['refhvrs'].append(refhvr_id)
                    else:
                        concat[id] = {}
                        concat[id]['refhvrs'] = [refhvr_id]
                    concat[id]['distance'] = distance



                #######################################
                #
                # Insert records into gast_concat_filename
                #
                #######################################
                # first we need to open the gast_filename
                gastconcat_fh     = open(gastconcat_filename, 'w')
                for id, value in concat.items():
                    #print('trying gastconcat', id, value)
                    gastconcat_fh.write( id + "\t" + concat[id]['distance'] + "\t" + ' '.join(concat[id]['refhvrs']) + "\n" )
                gastconcat_fh.close()

            else:
                self.logger.warning("No clustergast file found:"+clustergast_filename_single+"\nContinuing on ...")
                self.runobj.run_status_file_h.write(json.dumps({'status':'WARNING', 'message':"No clustergast file found: "+clustergast_filename_single+" Continuing"})+"\n")


        print("Finished gast_cleanup")
        self.logger.info("Finished gast_cleanup")
        return {'status':"GAST_SUCCESS", 'message':"gast_cleanup finished"}

    def gast2tax(self):
        """
        Creates taxtax files
        """
        self.runobj.run_status_file_h.write(json.dumps({'status':'STARTING_GAST2TAX'})+"\n")
        key_counter = 0
        qsub_prefix = 'gast2tax_sub_'
        #print(tax_file)
        tax_files = []
        qsub_id_list=[]
        for key in self.iterator:
            key_counter += 1
            'move to Dirs'
            if self.runobj.vamps_user_upload:
                output_dir = os.path.join(self.global_gast_dir, key)
                gast_dir = os.path.join(self.global_gast_dir, key)
                if self.runobj.platform == 'illumina':
                    # same file
                    fasta_file = os.path.join(output_dir, 'unique.fa')
                    unique_file = os.path.join(output_dir, 'unique.fa')
                else:
                    fasta_file = os.path.join(output_dir, 'fasta.fa')
                    unique_file = os.path.join(output_dir, 'unique.fa')

                names_file = os.path.join(output_dir, 'names')
                tagtax_file = os.path.join(output_dir, 'tagtax_terse')
                if os.path.exists(unique_file) and os.path.getsize(unique_file)>0:
                    tax_files.append(tagtax_file)
                #datasets_file = os.path.join(self.global_gast_dir, 'datasets')
            else:
                if self.runobj.platform == 'illumina':
                    output_dir = os.path.join(self.global_gast_dir, key)
                    gast_dir = os.path.join(self.global_gast_dir, key)
                    file_prefix = self.runobj.samples[key].file_prefix
                    unique_file = os.path.join(self.input_dir, file_prefix+"-PERFECT_reads.fa.unique")
                    names_file = os.path.join(self.input_dir, file_prefix+"-PERFECT_reads.fa.unique.names")
                elif self.runobj.platform == '454':
                    pass
                else:
                    sys.exit("gast2tax: no platform")

            'create dna_region in self'
            if key in self.runobj.samples:
                dna_region = self.runobj.samples[key].dna_region
            else:
                dna_region = self.runobj.dna_region
            if not dna_region:
                self.logger.error("gast2tax: We have no DNA Region: Setting dna_region to 'unknown'")
                self.runobj.run_status_file_h.write(json.dumps({'status':'WARNING', 'message':"gast2tax: We have no DNA Region: Setting dna_region to 'unknown'"})+"\n")
                dna_region = 'unknown'
            max_gast_distance = C.max_gast_distance['default']
            if dna_region in C.max_gast_distance:
                max_gast_distance = C.max_gast_distance[dna_region]


            if self.use_cluster:

                # create script - each file gets script
                script_filename = os.path.join(gast_dir, qsub_prefix + str(key_counter))
                fh = open(script_filename, 'w')
                qstat_name = "gast2tax" + key + '_' + self.runobj.run + "_" + str(key_counter)
                log_file = os.path.join(gast_dir, 'gast2tax.log_' + str(key_counter))
                fh.write("#!/bin/sh\n\n")
                #fh.write("#$ -j y\n" )
                #fh.write("#$ -o " + log_file + "\n")
                #fh.write("#$ -N " + qstat_name + "\n\n")

                # setup environment
                #fh.write("source /xraid/bioware/Modules/etc/profile.modules\n")
                #fh.write("module load bioware\n")
                #fh.write("export PYTHONPATH=/groups/vampsweb//:$PYTHONPATH\n\n")
                if self.utils.is_vamps():
                    pipeline_base = C.py_pipeline_base_vamps
                    clusterize = C.clusterize_cmd_vamps
                elif self.runobj.site == 'vamps' or self.runobj.site == 'vampsdev' or self.runobj.site == 'new_vamps':
                    calcnodes = C.calcnodes_cmd_vamps
                    clusterize = C.clusterize_cmd_vamps
                else:
                    pipeline_base = C.py_pipeline_base
                    clusterize = C.clusterize_cmd
                gast2tax_cmd = [pipeline_base+"gast2tax.py",
                                '-dna',dna_region,
                                '-key',key,
                                "-max",str(max_gast_distance),
                                '-o', gast_dir,
                                '-n',names_file,
                                '-site', self.runobj.site,
                                '--vamps_user_upload',
                                '-platform', self.runobj.platform
                                ]
                fh.write(' '.join(gast2tax_cmd)+"\n" )

                #fh.write("/xraid2-2/vampsweb/"+self.runobj.site+"/pipeline/gast2tax.py -dna "+dna_region+" -max "+str(max_gast_distance)+" -o "+gast_dir+" -n "+names_file+" -site "+self.runobj.site+"\n" )
                fh.close()

                # make script executable and run it
                os.chmod(script_filename, stat.S_IRWXU)

                opts = " -n 8 "
                #qsub_cmd = clusterize + " -log " + log_file + " -n 8 " + script_filename
                qsub_cmd = clusterize + " -log " + log_file + " " + script_filename
                # -log /xraid2-2/vampsweb/"+self.runobj.site+"/clusterize.log

                # on vamps and vampsdev qsub cannot be run - unless you call it from the
                # cluster aware directories /xraid2-2/vampsweb/vamps and /xraid2-2/vampsweb/vampsdev
                #qsub_cmd = C.qsub_cmd + " " + script_filename
                #qsub_cmd = C.clusterize_cmd + " " + script_filename


                subprocess.call(qsub_cmd, shell=True)

                self.logger.debug("qsub command: "+qsub_cmd)
                #subprocess.call(qsub_cmd, shell=True)
                #proc = subprocess.Popen(qsub_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                proc = subprocess.check_output(qsub_cmd, shell=True)
                self.logger.debug('proc: '+proc)
                try:
                    qsub_id = proc.split()[2]
                    # Your job 990889 ("clustergast_sub_46") has been submitted
                    qsub_id_list.append(qsub_id)
                except:
                    self.logger.debug('Could not split proc - Continuing on...')


            else:
                if os.path.exists(names_file) and os.path.getsize(names_file) > 0:
                    (refdb, taxdb) = self.get_reference_databases(dna_region)

                    ref_taxa = self.load_reftaxa(taxdb)

                    self.assign_taxonomy(key, gast_dir, dna_region, names_file, ref_taxa);


        if self.use_cluster:
            'check if clusterize is done'
            # wait here for tagtax files to finish
            temp_file_list = tax_files
            tagtax_terse_filename     = os.path.join(gast_dir, "tagtax_terse")
            tagtax_long_filename     = os.path.join(gast_dir, "tagtax_long")
            c = False
            maxwaittime = C.maxwaittime  # seconds
            sleeptime   = C.sleeptime    # seconds
            counter3 = 0
            print("Checking cluster jobs")
            result = self.waiting_on_cluster( self.runobj.site, qsub_id_list )
            time.sleep(10)

            print('gast2tax: cluster jobs are complete')

        print("Finished gast2tax")
        return {'status':"GAST_SUCCESS", 'message':"gast2tax finished"}


    def get_reference_databases(self, dna_region):

        #if dna region == v6v4(a) change it to v4v6
        # other reverse regions?
        if dna_region == 'v6v4':
            dna_region = 'v4v6'
        if dna_region == 'v6v4a':
            dna_region = 'v4v6a'
        print( 'dna_region ', dna_region)

        refdb = os.path.join(self.refdb_dir, 'refssu.fa')
        taxdb = os.path.join(self.refdb_dir, 'refssu.tax')
        self.db_type='db'
        if C.use_full_length or dna_region == 'unknown' or dna_region not in C.refdbs:
            refdb = os.path.join(self.refdb_dir, 'refssu.fa')
            taxdb = os.path.join(self.refdb_dir, 'refssu.tax')
            self.db_type='db'
        else:

            # try udb first
            if dna_region in C.refdbs:
                if os.path.exists(os.path.join(self.refdb_dir, C.refdbs[dna_region]+'.fa')):
                    refdb = os.path.join(self.refdb_dir, C.refdbs[dna_region]+'.fa')
                    taxdb = os.path.join(self.refdb_dir, 'ref'+dna_region+'.tax')
                    self.db_type='db'
                else:
                    #print('could not find refdb '+os.path.join(self.refdb_dir, C.refdbs[dna_region])+".udb - Using full length")
                    refdb = os.path.join(self.refdb_dir, 'refssu.fa')
                    taxdb = os.path.join(self.refdb_dir, 'refssu.tax')
                    self.db_type='db'
            elif os.path.exists(os.path.join(self.refdb_dir, 'ref'+dna_region+'.fa')):
                refdb = os.path.join(self.refdb_dir, 'ref'+dna_region+'.fa')
                taxdb = os.path.join(self.refdb_dir, 'ref'+dna_region+'.tax')
                self.db_type='db'

            elif os.path.exists(os.path.join(self.refdb_dir, 'refssu.fa')):

                refdb = os.path.join(self.refdb_dir, 'refssu.fa')
                taxdb = os.path.join(self.refdb_dir, 'refssu.tax')
                self.db_type='db'
            else:
                refdb = os.path.join(self.refdb_dir, 'refssu.fa')
                taxdb = os.path.join(self.refdb_dir, 'refssu.tax')
                self.db_type='db'
                self.logger.error("Could not find reference database in "+self.refdb_dir+" - Using full length")



        self.logger.info('tax_file: '+taxdb)
        self.logger.info('ref_file: '+refdb)
        return (refdb, taxdb)

    def get_fastasampler_cmd(self, unique_file, fastasamp_filename, start, end):
        fastasampler = C.fastasampler_cmd
        if self.utils.is_local():
            fastasampler = C.fastasampler_cmd_local
        elif self.utils.is_vamps():
            fastasampler = C.fastasampler_cmd_vamps
        fastasampler_cmd = fastasampler
        fastasampler_cmd += ' -n '+ str(start)+','+ str(end)
        fastasampler_cmd += " -delim '|' "
        fastasampler_cmd += ' ' + unique_file
        fastasampler_cmd += ' ' + fastasamp_filename
        return fastasampler_cmd


    def get_usearch_cmd(self, fastasamp_filename, refdb, usearch_filename, use_64bit=False  ):

        if use_64bit:
            # We don't have use of 64bit usearch anymore
            usearch_cmd = C.usearch64_cmd
            usearch_cmd += ' -usearch_global ' + fastasamp_filename
            usearch_cmd += ' -gapopen 6I/1E'
            usearch_cmd += ' -uc_allhits'
            usearch_cmd += ' -db ' + refdb
            usearch_cmd += ' -strand plus'
            #usearch_cmd += ' -notrunclabels'
            usearch_cmd += ' -uc ' + usearch_filename
            usearch_cmd += ' -maxaccepts ' + str(C.max_accepts)
            usearch_cmd += ' -maxrejects ' + str(C.max_rejects)
            usearch_cmd += ' -id ' + str(C.pctid_threshold)


        else:
            usearch_cmd = C.usearch6_cmd
            if self.utils.is_local():
                usearch_cmd = C.usearch6_cmd_local
                usearch_cmd = C.usearch5_cmd
            elif self.utils.is_vamps():
                usearch_cmd = C.vsearch_cmd_vamps

            usearch_cmd += ' -usearch_global ' + fastasamp_filename
            usearch_cmd += ' -gapopen 6I/1E'
            usearch_cmd += ' -uc_allhits'
            usearch_cmd += ' -db ' + refdb
            usearch_cmd += ' -strand plus'
            #usearch_cmd += ' -notrunclabels'
            usearch_cmd += ' -uc ' + usearch_filename
            usearch_cmd += ' -maxaccepts ' + str(C.max_accepts)
            usearch_cmd += ' -maxrejects ' + str(C.max_rejects)
            usearch_cmd += ' -id ' + str(C.pctid_threshold)


        return usearch_cmd

    def get_grep_cmd(self, usearch_filename, clustergast_filename ):

        use_full_length = ''
        if C.use_full_length:
            use_full_length = "-use_full_length"

        if hasattr(self.runobj, 'use_full_length') and self.runobj.use_full_length:
            use_full_length = "-use_full_length"

        grep_cmd = "grep"
        grep_cmd += " -P \"^H\\t\" " + usearch_filename + " |"
        #grep_cmd += " sed -e 's/|.*\$//' |"
        # changed grep command to remove frequency from read_id
        #grep_cmd += " sed -e 's/|frequency:[0-9]*//' |"
        #grep_cmd += " awk -F\"\\t\" '{print $9 \"\\t\" $4 \"\\t\" $10 \"\\t\" $8}' |"

        grep_cmd += " sed -e 's/|.*\$//' |"
        grep_cmd += " awk -F\"\\t\" '{print $9 \"\\t\" $4 \"\\t\" $10 \"\\t\" $8}' |"

        grep_cmd += " sort -k1,1b -k2,2gr |"
        # append to clustergast file:
        # split_defline adds frequency to gastv6 file (last field)

        tophit_cmd = "/bioware/linux/seqinfo/bin/python_pipeline/py_mbl_sequencing_pipeline/pipeline/clustergast_tophit"
        if self.utils.is_vamps():
            tophit_cmd = C.tophit_cmd_vamps
        grep_cmd += " "+tophit_cmd + " -split_defline_frequency "+use_full_length+" >> " + clustergast_filename

        return grep_cmd

    def load_reftaxa(self, tax_file):


        taxa ={}
        #open(TAX, "<$tax_file") || die ("Unable to open reference taxonomy file: $tax_file.  Exiting\n");
        #while (my $line = <TAX>)
        n=1
        for line in  open(tax_file, 'r'):

            # 0=ref_id, 1 = taxa, 2 = count
            data=line.strip().split("\t")
            if data[0] == 'refhvr_id':
                continue
            copies = []

            # foreach instance of that taxa
            for i in range(0, int(data[2])):

                # add that taxonomy to an array
                copies.append(data[1])

            # add that array to the array of all taxa for that ref, stored in the taxa hash
            if data[0] in taxa:
                taxa[data[0]].append(copies)
            elif copies:
                taxa[data[0]] =[copies]
            else:
                taxa[data[0]] =[]
            n += 1
        return taxa

    def assign_taxonomy(self, key, gast_dir, dna_region, names_file, ref_taxa):

        from py_mbl_sequencing_pipeline.pipeline.taxonomy import Taxonomy, consensus
        #results = uc_results
        results = {}

        try:
            self.runobj.run_status_file_h.write(json.dumps({'status':"STARTING_ASSIGN_TAXONOMY: "+key})+"\n")
        except:
            pass
        #test_read='FI1U8LC02GEF7N'
        # open gast_file to get results
        "to Dirs"
        tagtax_terse_filename     = os.path.join(gast_dir, "tagtax_terse")
        tagtax_long_filename     = os.path.join(gast_dir, "tagtax_long")
        tagtax_terse_fh = open(tagtax_terse_filename, 'w')
        tagtax_long_fh = open(tagtax_long_filename, 'w')
        tagtax_long_fh.write("\t".join(["read_id", "taxonomy", "distance", "rank", "refssu_count", "vote", "minrank", "taxa_counts", "max_pcts", "na_pcts", "refhvr_ids"])+"\n")
        gast_file          = os.path.join(gast_dir, "gast"+dna_region)
        print(gast_file)
        if not os.path.exists(gast_file):
            self.logger.info("gast:assign_taxonomy: Could not find gast file: "+gast_file+". Returning")
            return results

        for line in  open(gast_file, 'r'):
            # must split on tab because last field may be empty and must be maintained as blank
            data=line.strip().split("\t")
            if len(data) == 3:
                data.append("")
            # 0=id, 1=ref, 2=dist, 3=align 4=frequency
            #if data[0]==test_read:
            #    print('found test in gastv6 ', data[1].split('|')[0], data[2], data[3])

            read_id = data[0]
            if read_id in results:
                results[read_id].append( [data[1].split('|')[0], data[2], data[3], data[4]] )
            else:
                results[read_id]=[ [data[1].split('|')[0], data[2], data[3], data[4]] ]


        for line in open(names_file, 'r'):
            data=line.strip().split("\t")
            dupes = data[1].split(",")
            read_id  = data[0]
            taxObjects  = []
            distance    = 0
            frequency   = 0
            refs_for    = {}

            #print('read_id', read_id)
            'assing taxonomyt method, either fake or real'
            if read_id not in results:
                results[read_id]=["Unknown", '1', "NA", '0', '0', "NA", "0;0;0;0;0;0;0;0", "0;0;0;0;0;0;0;0", "100;100;100;100;100;100;100;100"]
                refs_for[read_id] = [ "NA" ]
            else:
                'it is in results[]'
                #print('read_id in res', read_id, results[read_id])
                #if read_id == test_read_id:
                #    print('found ', test_read_id, results[test_read_id])
                for i in range( 0, len(results[read_id])):
                    #for resultread_id in results[read_id]:
                    #print('resread_id', results[read_id])
                    ref = results[read_id][i][0]
                    if ref in ref_taxa:
                        for tax in ref_taxa[ref]:
                            for t in tax:
                                taxObjects.append(Taxonomy(t))
                    else:
                        pass

                    if read_id in refs_for:
                        #if read_id ==test_read_id:
                        #    print('2', read_id, refs_for[test_read_id])
                        if results[read_id][i][0] not in refs_for[read_id]:
                            refs_for[read_id].append(results[read_id][i][0])
                    else:
                        #if read_id == test_read_id:
                        #    print('1', read_id, results[read_id][i][0])
                        refs_for[read_id] = [results[read_id][i][0]]

                    # should all be the same distance for the duplicates
                    distance = results[read_id][i][1]
                    frequency = results[read_id][i][3]
                #Lookup the consensus taxonomy for the array
                taxReturn = consensus(taxObjects, C.majority)

                # 0=taxObj, 1=winning vote, 2=minrank, 3=rankCounts, 4=maxPcts, 5=naPcts;
                taxon = taxReturn[0].taxstring()
                #if taxon[-3:] = ';NA':
                #    taxon = taxon[:-3]
                #tax_counter[taxon]
                rank = taxReturn[0].depth()
                #print(read_id, taxon, rank, taxReturn[0], taxReturn[1])
                if not taxon: taxon = "Unknown"

                # (taxonomy, distance, rank, refssu_count, vote, minrank, taxa_counts, max_pcts, na_pcts)
                results[read_id] = [ taxon, str(distance), rank, str(len(taxObjects)), str(taxReturn[1]), taxReturn[2], taxReturn[3], taxReturn[4], taxReturn[5] ]
                #print("\t".join([read_id, taxon, str(distance), rank, str(len(taxObjects)), str(taxReturn[1]), taxReturn[2], taxReturn[3], taxReturn[4], taxReturn[5]]) + "\n")
#read_id_id taxonomy        distance        rank    refssu_count    vote    minrank taxa_counts     max_pcts        na_pcts refhvr_ids
#D4ZHLFP1:25:B022DACXX:3:1101:12919:40734 1:N:0:TGACCA|frequency:162     Bacteria;Proteobacteria;Gammaproteobacteria     0.117   class   2       100     genus   1;1;1;2;2;2;0;0 100;100;100;50;50;50;0;0        0;0;0;0;0;0;100;100     v6_CI671
#D4ZHLFP1:25:B022DACXX:3:1101:10432:76870 1:N:0:TGACCA|frequency:105     Bacteria;Proteobacteria;Gammaproteobacteria     0.017   class   1       100     class   1;1;1;0;0;0;0;0 100;100;100;0;0;0;0;0   0;0;0;100;100;100;100;100       v6_BW306

            # Replace hash with final taxonomy results, for each copy of the sequence
            for d in dupes:
               # print(OUT join("\t", $d, @{$results{$read_id}}, join(", ", sort @{$refs_for{$read_id}})) . "\n";)
                d = d.strip()
                tagtax_long_fh.write( d+"\t"+"\t".join(results[read_id])+"\t"+', '.join(sorted(refs_for[read_id]))  + "\n")
                tagtax_terse_fh.write(d+"\t"+results[read_id][0]+"\t"+results[read_id][2]+"\t"+results[read_id][3]+"\t"+', '.join(sorted(refs_for[read_id]))+"\t"+results[read_id][1]+"\t"+str(frequency)+"\n")

        tagtax_terse_fh.close()
        tagtax_long_fh.close()
        return results

#    def create_uniques_from_fasta(self, fasta_file, key):
#
#         mothur_cmd = C.mothur_cmd+" \"#unique.seqs(fasta="+fasta_file+", outputdir="+os.path.join(self.basedir, key)+"/);\"";
#
#         #mothur_cmd = site_base+"/clusterize_vamps -site vampsdev -rd "+user+"_"+runcode+"_gast -rc "+runcode+" -u "+user+" /bioware/mothur/mothur \"#unique.seqs(fasta="+fasta_file+");\"";
#         subprocess.call(mothur_cmd, shell=True)
    def check_for_unique_files(self, keys):
        self.logger.info("Checking for uniques file")
        for key in keys:
            if self.runobj.vamps_user_upload:
                # one fasta file or (one project and dataset from db)
                # if self.runobj.fasta_file is not None then we should have multiple datasets
                # which have already been uniqued
                if self.runobj.fasta_file and os.path.exists(self.runobj.fasta_file):
                    #output_dir = os.path.join(self.basedir, keys[0])
                    unique_file = os.path.join(self.global_gast_dir, key, 'unique.fa')
                    names_file = os.path.join(self.global_gast_dir, key, 'names')

                    # the -x means do not store frequency data in defline of fasta file
                    fastaunique_cmd = C.fastaunique_cmd +" -x -i "+self.runobj.fasta_file+" -o "+unique_file+" -n "+names_file
                    print(fastaunique_cmd)

                    subprocess.call(fastaunique_cmd, shell=True)

                    #shutil.move('a.txt', 'b.kml')
                    #os.rename(filename, filename[7:])
                    #os.rename(filename, filename[7:])
                else:
                    if self.runobj.project and self.runobj.dataset:
                        pass
                    else:
                        pass
                #get from database
            else:
                if self.runobj.platform == 'illumina':
#                    reads_dir = dirs.check_dir(dirs.reads_overlap_dir)
#                    os.path.join(self.analysis_dir, 'reads_overlap')

                    file_prefix = key
                    unique_file = os.path.join(self.reads_dir, file_prefix+"-PERFECT_reads.fa.unique")
                    if os.path.exists(unique_file):
                        if os.path.getsize(unique_file) > 0:
                            self.logger.debug( "GAST: Found uniques file: "+unique_file)
                        else:
                            self.logger.warning( "GAST: Found uniques file BUT zero size "+unique_file)
                            continue
                    else:
                        self.logger.error( "GAST: NO uniques file found "+unique_file)


                if self.runobj.platform == '454':
                    pass
                else:
                    pass


        return {"status":"GAST_SUCCESS", "message":"checking for uniques"}

    def get_fasta_from_database(self):
        pass

    def get_qstat_id_list(self, site):

        # ['139239', '0.55500', 'usearch', 'avoorhis', 'r', '01/22/2012', '09:00:39', 'all.q@grendel-07.bpcservers.pr', '1']
        # 1) id
        # 2)
        # 3) name
        # 4) username
        # 5) code r=running, Ew=Error
        web_user = site+'httpd'
        qstat_user = subprocess.check_output(['whoami'])
        qstat_cmd = ['qstat', '-u', qstat_user.strip()]
        print(' qstat cmd: ',qstat_cmd)
        qstat_codes={}
        output = subprocess.check_output(qstat_cmd)
        #print(output)
        output_list = output.strip().split("\n")[2:]
        qstat_codes['id'] = [n.split()[0] for n in output_list]
        qstat_codes['name'] = [n.split()[2] for n in output_list]
        qstat_codes['user'] = [n.split()[3] for n in output_list]
        qstat_codes['code'] = [n.split()[4] for n in output_list]
        #print('Found IDs',qstat_ids)

        return qstat_codes

    def waiting_on_cluster(self, site, my_working_id_list):
        print('my_working_id_list',my_working_id_list)
        c = False
        maxwaittime = C.maxwaittime  # 50000 seconds
        sleeptime   = C.sleeptime    # 5 seconds
        wait_counter = 0
        #print(maxwaittime,sleeptime)
        time.sleep(sleeptime)
        got_one = False
        while my_working_id_list:

            qstat_codes = self.get_qstat_id_list(site)
            #print('qstat_codes',qstat_codes['id'])
            if not qstat_codes['id']:
                #print('No qstat ids')
                #print("id list not found: may need to increase initial_interval if you haven't seen running ids.")
                print('qstat id list not found')
                if not got_one:
                    # empty out list we have seen some ids and now empty
                    my_working_id_list = []
            if 'Eqw' in qstat_codes['code']:
                print( "Check cluster: may have error code(s), but they may not be mine!")

            got_one = False

            #print('working ids',my_working_id_list)
            #for id in my_working_id_list:
            #    if id not in qstat_codes['id']:

            if my_working_id_list and my_working_id_list[0] in qstat_codes['id']:

                got_one = True
                name = qstat_codes['name'][qstat_codes['id'].index(my_working_id_list[0])]
                user = qstat_codes['user'][qstat_codes['id'].index(my_working_id_list[0])]
                code = qstat_codes['code'][qstat_codes['id'].index(my_working_id_list[0])]


                if code[:1] == 'E':
                    print('FAIL','Found Eqw code',my_working_id_list[0])
                elif code == 'qw':
                    print("id is still queued: " +  str(my_working_id_list[0]) + " " + str(code))
                    wait_counter = 0  # gets reset to '0' when id is still queued
                elif code == 'r':
                    print(my_working_id_list[0],"is running...")
                    wait_counter = 0  # gets reset to '0' when id is stll running

                else:
                    print('Unknown qstat code: ' + str(code))
            elif my_working_id_list:
                # here we did NOT find the id: my_working_id_list[0] in the list of ids from qstat -u
                # so we assume it is done.
                print('removing: ', my_working_id_list[0])
                my_working_id_list = my_working_id_list[1:]  # pop it off and throw it away
                wait_counter = 0  # gets reset to '0' when an id is found/removed

            print('my_working_id_list length:',len(my_working_id_list))
            wait_counter +=1
            time.sleep(sleeptime)
            # using a counter that gets reset (max_wait_counter) when an id is found/removed
            if wait_counter >= maxwaittime:
                print('FAIL','Max Count exceeded: ',maxwaittime)
                sys.exit('Max Count exceeded')
