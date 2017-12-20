import sys
import os
import constants as C
from subprocess import Popen, PIPE
from shlex import split
from time import sleep, time, gmtime, strftime

from pipeline.get_ini import readCSV
from pipeline.pipelinelogging import logger
from pipeline.utils import Dirs, PipelneUtils
import IlluminaUtils.lib.fastalib as fastalib
from collections import defaultdict

try:
    import MySQLdb
except MySQLdb.Error, e:
    message = """
    MySQLdb ERROR
      To load the correct module, try running these commands before running the pipeline:
       
source /xraid/bioware/Modules/etc/profile.modules
module load bioware
    """
    PipelneUtils.print_both(message)
    PipelneUtils.print_both("Error %d: %s" % (e.args[0], e.args[1]))
    raise
except:                       # catch everything
#     PipelneUtils.print_both("Unexpected:")
    print "Unexpected:"         # handle unexpected exceptions
#     PipelneUtils.print_both(sys.exc_info()[0])
    print sys.exc_info()[0]     # info about curr exception (type,value,traceback)
    raise          

#     sys.exit("""
#     MySQLdb ERROR
#       To load the correct module, try running these commands before running the pipeline:
#       
# source /xraid/bioware/Modules/etc/profile.modules
# module load bioware
# 
#     """)
class MyConnection:
    """
    Connection to env454
    Takes parameters from ~/.my.cnf, default host = "vampsdev", db="test"
    if different use my_conn = MyConnection(host, db)
    """
    def __init__(self, host="bpcweb7", db="test"):
# , read_default_file=os.path.expanduser("~/.my.cnf"), port = 3306
        
        self.utils  = PipelneUtils()        
        self.conn   = None
        self.cursor = None
        self.rows   = 0
        self.new_id = None
        self.lastrowid = None
        
        try:           
            self.utils.print_both("=" * 40)
            self.utils.print_both("host = " + str(host) + ", db = "  + str(db))
            self.utils.print_both("=" * 40)
            read_default_file = os.path.expanduser("~/.my.cnf")
            port_env = 3306
            
            if self.utils.is_local():
                host = "127.0.0.1"
#                 if db == "env454":
#                     port_env = 3308
#                     read_default_file = os.path.expanduser("~/.my.cnf_server")
#                 else:
#                     db = "test_env454"
                read_default_file = "~/.my.cnf_local"
            self.conn   = MySQLdb.connect(host = host, db = db, read_default_file = read_default_file, port = port_env)
            self.cursor = self.conn.cursor()
            # self.escape = self.conn.escape()
                   
        except MySQLdb.Error, e:
            self.utils.print_both("Error %d: %s" % (e.args[0], e.args[1]))
            raise
        except:                       # catch everything
            self.utils.print_both("Unexpected:")
            self.utils.print_both(sys.exc_info()[0])
#             print "Unexpected:"         # handle unexpected exceptions
#             print sys.exc_info()[0]     # info about curr exception (type,value,traceback)
            raise                       # re-throw caught exception   

    def execute_fetch_select(self, sql):
        if self.cursor:
          try:
            # sql = self.conn.escape(sql)
            self.cursor.execute(sql)
            res = self.cursor.fetchall ()
          except:
            self.utils.print_both(("ERROR: query = %s") % sql)
            raise
          return res

    def execute_no_fetch(self, sql):
        if self.cursor:
            self.cursor.execute(sql)
            self.conn.commit()
#            if (self.conn.affected_rows()):
#            print dir(self.cursor)
            return self.cursor.lastrowid
#        logger.debug("rows = "  + str(self.rows))
 

class dbUpload:
    """db upload methods"""
    Name = "dbUpload"
    """
    TODO: add tests and test case
    TODO: change hardcoded values to args: 
        self.sequence_table_name = "sequence_ill", 
        self.sequence_field_name = "sequence_comp"  
    TODO: generalize all bulk uploads and all inserts? to not copy and paste
    TODO: add refssu_id
    TODO: change csv validaton for new fields
    Order:
        # put_run_info
        # insert_seq()
        # insert_pdr_info()
        # gast
        # insert_taxonomy()
        # insert_sequence_uniq_info_ill()

    """
    def __init__(self, runobj = None, db_server = None):
        if db_server is None:
            db_server = "env454"
        self.db_server   = db_server 
        self.utils       = PipelneUtils()
        self.runobj      = runobj
        self.rundate     = self.runobj.run
        self.use_cluster = 1       
        self.unique_fasta_files = []
#        if self.runobj.vamps_user_upload:
#            site       = self.runobj.site
#            dir_prefix = self.runobj.user + '_' + self.runobj.run
#        else:
#            site = ''
#            dir_prefix = self.runobj.run         
#        dirs = Dirs(self.runobj.vamps_user_upload, dir_prefix, self.runobj.platform, site = site)

        if self.runobj.vamps_user_upload:
            site = self.runobj.site
            dir_prefix=self.runobj.user+'_'+self.runobj.run
        else:
            site = ''
            dir_prefix = self.runobj.run
        if self.runobj.lane_name:
            lane_name = self.runobj.lane_name
        else:
            lane_name = ''
        
        self.dirs = Dirs(self.runobj.vamps_user_upload, dir_prefix, self.runobj.platform, lane_name = lane_name, site = site) 
 
        
        self.analysis_dir = self.dirs.check_dir(self.dirs.analysis_dir)
        self.fasta_dir    = self.dirs.check_dir(self.dirs.reads_overlap_dir)
        self.gast_dir     = self.dirs.check_dir(self.dirs.gast_dir)

        host_name     = runobj.database_host
        database_name = runobj.database_name
        
        self.filenames   = []
        # logger.error("self.utils.is_local() LLL1 db upload")
        # logger.error(self.utils.is_local())
        
        self.sequence_field_name = "sequence_comp" 

#         TODO: make a dict
        if (self.db_server == "vamps2"):
            self.sequence_table_name = "sequence" 
            self.sequence_pdr_info_table_name = "sequence_pdr_info"
            if self.utils.is_local():
                self.my_conn = MyConnection(host = 'localhost', db="vamps2")
            else:
                self.my_conn = MyConnection(host='vampsdb', db="vamps2")
        
        elif (self.db_server == "env454"):
            self.sequence_table_name = "sequence_ill" 
            self.sequence_pdr_info_table_name = "sequence_pdr_info_ill"
            if self.utils.is_local():
                self.my_conn = MyConnection(host = 'localhost', db="test_env454")
            else:
                self.my_conn = MyConnection(host='bpcdb1', db="env454")

#             self.my_conn = MyConnection(host='bpcdb1.jbpc-np.mbl.edu', db="env454")

        self.taxonomy    = Taxonomy(self.my_conn)
        self.my_csv      = None

        self.unique_file_counts = self.dirs.unique_file_counts
        self.dirs.delete_file(self.unique_file_counts)
        self.seq_id_dict = {}
        self.taxonomies = set()
        self.run_id      = None
#        self.nonchimeras_suffix = ".nonchimeric.fa"
        self.nonchimeric_suffix = "." + C.nonchimeric_suffix #".nonchimeric.fa"
        self.fa_unique_suffix   = ".fa." + C.unique_suffix #.fa.unique
        self.v6_unique_suffix   = "MERGED_V6_PRIMERS_REMOVED." + C.unique_suffix
        self.suff_list = [self.nonchimeric_suffix, self.fa_unique_suffix, self.v6_unique_suffix]

#         self.merge_unique_suffix = "." + C.filtered_suffix + "." + C.unique_suffix #.MERGED-MAX-MISMATCH-3.unique
        self.suffix_used        = ""
        
#        self.refdb_dir = '/xraid2-2/vampsweb/blastdbs/'
   
   
    def get_fasta_file_names(self):
        files_names = self.dirs.get_all_files(self.fasta_dir)
        self.unique_fasta_files = [f for f in files_names.keys() if f.endswith(tuple(self.suff_list))]
# needs return because how it's called from pipelineprocesor
        return self.unique_fasta_files
        

    def get_run_info_ill_id(self, filename_base):
        
        my_sql = """SELECT run_info_ill_id FROM run_info_ill 
                    JOIN run using(run_id)
                    WHERE file_prefix = '%s'
                    and run = '%s';
        """ % (filename_base, self.rundate)
        res    = self.my_conn.execute_fetch_select(my_sql)
        if res:
            return int(res[0][0])
        
    
        
    def make_seq_upper(self, filename):
        read_fasta = fastalib.ReadFasta(filename)
        sequences  = [seq.upper() for seq in read_fasta.sequences] #here we make uppercase for VAMPS compartibility    
        read_fasta.close()
        return sequences 
        
    def insert_seq(self, sequences):
        query_tmpl = "INSERT INTO %s (%s) VALUES (COMPRESS(%s))"
        val_tmpl   = "'%s'"
        my_sql     = query_tmpl % (self.sequence_table_name, self.sequence_field_name, ')), (COMPRESS('.join([val_tmpl % key for key in sequences]))
        my_sql     = my_sql + " ON DUPLICATE KEY UPDATE %s = VALUES(%s);" % (self.sequence_field_name, self.sequence_field_name)
#       print "MMM my_sql = %s" % my_sql
        seq_id     = self.my_conn.execute_no_fetch(my_sql)
        self.utils.print_both("sequences in file: %s\n" % (len(sequences)))
        return seq_id
        
    def get_seq_id_dict(self, sequences):
        id_name    = self.sequence_table_name + "_id" 
        query_tmpl = """SELECT %s, uncompress(%s) FROM %s WHERE %s in (COMPRESS(%s))"""
        val_tmpl   = "'%s'"
        try:
            my_sql     = query_tmpl % (id_name, self.sequence_field_name, self.sequence_table_name, self.sequence_field_name, '), COMPRESS('.join([val_tmpl % key for key in sequences]))
            res        = self.my_conn.execute_fetch_select(my_sql)
            one_seq_id_dict = dict((y, int(x)) for x, y in res)
            self.seq_id_dict.update(one_seq_id_dict)
        except:
            if len(sequences) == 0:
                self.utils.print_both(("ERROR: There are no sequences, please check if there are correct fasta files in the directory %s") % self.fasta_dir)
            raise


    def get_id(self, table_name, value):
        id_name = table_name + '_id'
        my_sql  = """SELECT %s FROM %s WHERE %s = '%s';""" % (id_name, table_name, table_name, value)
        res     = self.my_conn.execute_fetch_select(my_sql)
        if res:
            return int(res[0][0])         
            
    def get_sequence_id(self, seq):
        my_sql = """SELECT %s_id FROM sequence_ill WHERE COMPRESS('%s') = sequence_comp;""" % (seq, self.sequence_table_name)
        res    = self.my_conn.execute_fetch_select(my_sql)
        if res:
            return int(res[0][0])     
    
    def insert_pdr_info(self, fasta, run_info_ill_id):
#         res_id = ""
        if (not run_info_ill_id):
            self.utils.print_both("ERROR: There is no run info yet, please check if it's uploaded to env454")
            
        # ------- insert sequence info per run/project/dataset --------
        seq_upper = fasta.seq.upper()
        sequence_id = self.seq_id_dict[seq_upper]

        seq_count       = int(fasta.id.split('|')[-1].split(':')[-1])
#        print run_info_ill_id, sequence_ill_id, seq_count
        my_sql          = "INSERT INTO %s (run_info_ill_id, %s_id, seq_count) VALUES (%s, %s, %s)" % (self.sequence_pdr_info_table_name, self.sequence_table_name, run_info_ill_id, sequence_id, seq_count)
        my_sql          = my_sql + " ON DUPLICATE KEY UPDATE run_info_ill_id = VALUES(run_info_ill_id), %s_id = VALUES(%s_id), seq_count = VALUES(seq_count);" % (self.sequence_table_name, self.sequence_table_name)
#         print "MMM1 my_sql = %s" % my_sql
#         try:
#             res_id = self.my_conn.execute_no_fetch(my_sql)
#             return res_id
#         except:
#             self.utils.print_both("Offensive query: %s" % my_sql)
#             raise
        return my_sql
        
    
    def insert_pdr_info2(self, fasta, run_info_ill_id):
#         res_id = ""
        if (not run_info_ill_id):
            self.utils.print_both("ERROR: There is no run info yet, please check if it's uploaded to env454")
            
        # ------- insert sequence info per run/project/dataset --------
        seq_upper = fasta.seq.upper()
        sequence_id = self.seq_id_dict[seq_upper]

        seq_count       = int(fasta.id.split('|')[-1].split(':')[-1])
#        print run_info_ill_id, sequence_ill_id, seq_count
#         my_sql          = "INSERT INTO sequence_pdr_info (`dataset_id`, sequence_id, seq_count, classifier_id) VALUES ((SELECT dataset_id FROM run_info_ill WHERE run_info_ill.run_info_ill_id = 372), 5643752, 1, 2)" 


        my_sql          = "INSERT INTO %s (dataset_id, %s_id, seq_count) VALUES ((SELECT dataset_id FROM run_info_ill WHERE run_info_ill.run_info_ill_id = %s), %s, %s)" % (self.sequence_pdr_info_table_name, self.sequence_table_name, run_info_ill_id, sequence_id, seq_count)
        my_sql          = my_sql + " ON DUPLICATE KEY UPDATE dataset_id = VALUES(dataset_id), %s_id = VALUES(%s_id), seq_count = VALUES(seq_count);" % (self.sequence_table_name, self.sequence_table_name)
#         print "MMM1 my_sql = %s" % my_sql
#         try:
#             res_id = self.my_conn.execute_no_fetch(my_sql)
#             return res_id
#         except:
#             self.utils.print_both("Offensive query: %s" % my_sql)
#             raise
        return my_sql
        
    def make_gast_files_dict(self):
        return self.dirs.get_all_files(self.gast_dir, "gast")
        
        
    def gast_filename(self, filename):
#         todo: if filename in make_gast_files_dict, use it full path
        gast_file_names = self.make_gast_files_dict()
        gast_file_name_path = ""
        for gast_file_name_path, tpls in gast_file_names.iteritems():
            if any(t.endswith(filename) for t in tpls):
                return gast_file_name_path 
    
    def get_gast_result(self, filename):
        gast_file_name = self.gast_filename(filename)
        self.utils.print_both("current gast_file_name = %s." % gast_file_name)
        
        try:
            with open(gast_file_name) as fd:
                gast_dict = dict([(l.split("\t")[0], l.split("\t")[1:]) for l in fd])    
            return gast_dict
        except IOError, e:
#            print dir(e)
#['__class__', '__delattr__', '__dict__', '__doc__', '__format__', '__getattribute__', '__getitem__', '__getslice__', '__hash__', '__init__', '__new__', '__reduce__', '__reduce_ex__', '__repr__', '__setattr__', '__setstate__', '__sizeof__', '__str__', '__subclasshook__', '__unicode__', 'args', 'errno', 'filename', 'message', 'strerror']
#            print "errno = %s" % e.errno
            logger.debug("errno = %s" % e.errno)
            if e.errno == 2:
                # suppress "No such file or directory" error
                pass            
#         except OSError, e:
        except TypeError, e:
            self.utils.print_both("Check if there is a gast file under %s for %s." % (self.gast_dir, filename))
            pass            
        except:
            # reraise the exception, as it's an unexpected error
            raise     
            
#     def get_taxonomy_id_dict(self):
# #         sequences  = [seq.upper() for seq in read_fasta.sequences] #here we make uppercase for VAMPS compartibility    
#          
#         my_sql = "SELECT %s, %s FROM %s;" % ("taxonomy_id", "taxonomy", "taxonomy")
#         res        = self.my_conn.execute_fetch_select(my_sql)
#         one_tax_id_dict = dict((y, int(x)) for x, y in res)
#         self.tax_id_dict.update(one_tax_id_dict)        

    def insert_sequence_uniq_info_ill(self, fasta, gast_dict):
        my_sql = ""
        if gast_dict:
            (taxonomy, distance, rank, refssu_count, vote, minrank, taxa_counts, max_pcts, na_pcts, refhvr_ids) = gast_dict[fasta.id]
            seq_upper = fasta.seq.upper()
            sequence_id = self.seq_id_dict[seq_upper]
# TEMP!
#             taxonomy_id = self.get_id("taxonomy", taxonomy)

            if taxonomy in self.taxonomy.tax_id_dict:
                try:
                    taxonomy_id = self.taxonomy.tax_id_dict[taxonomy] 
                    my_sql = """INSERT IGNORE INTO sequence_uniq_info_ill (%s_id, taxonomy_id, gast_distance, refssu_count, rank_id, refhvr_ids) VALUES
                   (
                    %s,
                    %s,
                    '%s',
                    '%s',
                    (SELECT rank_id FROM rank WHERE rank = '%s'),
                    '%s'                
                   )
                   ON DUPLICATE KEY UPDATE
                       updated = (CASE WHEN taxonomy_id <> %s THEN NOW() ELSE updated END),
                       taxonomy_id = %s,
                       gast_distance = '%s',
                       refssu_count = '%s',
                       rank_id = (SELECT rank_id FROM rank WHERE rank = '%s'),
                       refhvr_ids = '%s';
                   """ % (self.sequence_table_name, sequence_id, taxonomy_id, distance, refssu_count, rank, refhvr_ids.rstrip(), taxonomy_id, taxonomy_id, distance, refssu_count, rank, refhvr_ids.rstrip())
                except Exception, e:
                    logger.debug("Error = %s" % e)
                    raise

#             res_id = self.my_conn.execute_no_fetch(my_sql)
            return my_sql

    def put_run_info(self, content = None):

        run_keys = list(set([run_key.split('_')[1] for run_key in self.runobj.run_keys]))
        self.insert_bulk_data('run_key', run_keys)
        dna_regions = list(set([self.runobj.samples[key].dna_region for key in self.runobj.samples]))
        self.insert_bulk_data('dna_region', dna_regions)
        self.insert_rundate()

        for key in self.runobj.samples:
            value = self.runobj.samples[key]
            self.get_contact_v_info()
            contact_id = self.get_contact_id(value.data_owner)
            self.insert_project(value, contact_id)
            self.insert_dataset(value) 

            self.insert_run_info(value)

    def insert_bulk_data(self, key, values):
        query_tmpl = "INSERT IGNORE INTO %s (%s) VALUES (%s)"
        val_tmpl   = "'%s'"
        my_sql     = query_tmpl % (key, key, '), ('.join([val_tmpl % key for key in values]))
        self.my_conn.execute_no_fetch(my_sql)
    
    def get_contact_v_info(self):
        """
        TODO: get info from Hilary? from vamps?
        """
        pass
    def insert_test_contact(self):
        my_sql = '''INSERT IGNORE INTO contact (contact, email, institution, vamps_name, first_name, last_name)
                VALUES ("guest user", "guest@guest.com", "guest institution", "guest", "guest", "user");'''
        self.my_conn.execute_no_fetch(my_sql)        
        
    def get_contact_id(self, data_owner):
        my_sql = """SELECT contact_id FROM contact WHERE vamps_name = '%s';""" % (data_owner)
        res    = self.my_conn.execute_fetch_select(my_sql)
        if res:
            return int(res[0][0])        

    def insert_rundate(self):
        my_sql = """INSERT IGNORE INTO run (run, run_prefix, platform) VALUES
            ('%s', 'illumin', '%s');""" % (self.rundate, self.runobj.platform)
        self.run_id = self.my_conn.execute_no_fetch(my_sql)
        
    def insert_project(self, content_row, contact_id):
        if (not contact_id):
            self.utils.print_both("ERROR: There is no such contact info on env454, please check if the user has an account on VAMPS")        
        my_sql = """INSERT IGNORE INTO project (project, title, project_description, rev_project_name, funding, env_sample_source_id, contact_id) VALUES
        ('%s', '%s', '%s', reverse('%s'), '%s', '%s', %s);
        """ % (content_row.project, content_row.project_title, content_row.project_description, content_row.project, content_row.funding, content_row.env_sample_source_id, contact_id)
        self.utils.print_both(my_sql)
        self.my_conn.execute_no_fetch(my_sql)

    def insert_dataset(self, content_row):
        """
        TODO: get dataset_description
        """        
        my_sql = """INSERT IGNORE INTO dataset (dataset, dataset_description) VALUES
        ('%s', '');
        """ % (content_row.dataset)
        self.my_conn.execute_no_fetch(my_sql)
    
    def insert_run_info(self, content_row):
        run_key_id      = self.get_id('run_key',      content_row.run_key)
        if not (self.run_id):
            self.run_id = self.get_id('run',          self.rundate)
        dataset_id      = self.get_id('dataset',      content_row.dataset)
        project_id      = self.get_id('project',      content_row.project)
        dna_region_id   = self.get_id('dna_region',   content_row.dna_region)
        primer_suite_id = self.get_id('primer_suite', content_row.primer_suite)
        illumina_index_id = self.get_id('illumina_index', content_row.barcode_index)
        file_prefix     = content_row.barcode_index + "_" + content_row.run_key + "_" + content_row.lane
        #overlap = content_row.overlap
        #if (content_row.overlap == 'complete'):
        #    overlap = 0
        
        my_sql = """INSERT IGNORE INTO run_info_ill (run_key_id, run_id, lane, dataset_id, project_id, tubelabel, barcode, 
                                                    adaptor, dna_region_id, amp_operator, seq_operator, overlap, insert_size, 
                                                    file_prefix, read_length, primer_suite_id, platform, illumina_index_id) 
                                            VALUES (%s, %s, %s, %s, %s, '%s', '%s',  
                                                    '%s', %s, '%s', '%s', '%s', %s, 
                                                    '%s', %s, %s, '%s', %s);
        """ % (run_key_id, self.run_id, content_row.lane, dataset_id, project_id, content_row.tubelabel, content_row.barcode, 
               content_row.adaptor, dna_region_id, content_row.amp_operator, content_row.seq_operator, content_row.overlap, content_row.insert_size,
                                                    file_prefix, content_row.read_length, primer_suite_id, self.runobj.platform, illumina_index_id)
        
        self.utils.print_both("insert run_info sql = %s" % my_sql)
        
        self.my_conn.execute_no_fetch(my_sql)

    def insert_primer(self):
        pass
        
    def del_sequence_pdr_info_by_project_dataset(self, projects = "", datasets = "", primer_suite = ""):
        my_sql1 = """DELETE FROM %s
                    USING %s JOIN run_info_ill USING (run_info_ill_id) 
                    JOIN run USING(run_id) 
                    JOIN project using(project_id)
                    JOIN dataset using(dataset_id)
                    JOIN primer_suite using(primer_suite_id)
                    WHERE primer_suite = "%s"
                    AND run = "%s"
                """ % (self.sequence_pdr_info_table_name, self.sequence_pdr_info_table_name,  primer_suite, self.rundate)
        my_sql2 = " AND project in (" + projects + ")"
        my_sql3 = " AND dataset in (" + datasets + ")"
        if (projects == "") and (datasets == ""):
            my_sql = my_sql1
        elif (projects != "") and (datasets == ""):
            my_sql = my_sql1 + my_sql2
        elif (projects == "") and (datasets != ""):
            my_sql = my_sql1 + my_sql3
        elif (projects != "") and (datasets != ""):
            my_sql = my_sql1 + my_sql2 + my_sql3
        self.my_conn.execute_no_fetch(my_sql)

    def del_run_info_by_project_dataset(self, projects = "", datasets = "", primer_suite = ""):
        my_sql1 = """DELETE FROM run_info_ill
                    USING run_info_ill 
                    JOIN run USING(run_id) 
                    JOIN project using(project_id)
                    JOIN primer_suite using(primer_suite_id)
                    WHERE primer_suite = "%s"
                    AND run = "%s"
                """ % (primer_suite, self.rundate)
        my_sql2 = " AND project in (" + projects + ")"
        my_sql3 = " AND dataset in (" + datasets + ")"
        if (projects == "") and (datasets == ""):
            my_sql = my_sql1
        elif (projects != "") and (datasets == ""):
            my_sql = my_sql1 + my_sql2
        elif (projects == "") and (datasets != ""):
            my_sql = my_sql1 + my_sql3
        elif (projects != "") and (datasets != ""):
            my_sql = my_sql1 + my_sql2 + my_sql3
        self.my_conn.execute_no_fetch(my_sql)


    def del_sequence_uniq_info(self):
        my_sql = """DELETE FROM sequence_uniq_info_ill 
                    USING sequence_uniq_info_ill 
                    LEFT JOIN %s USING(%s_id) 
                    WHERE %s_id is NULL;""" % (self.sequence_pdr_info_table_name, self.sequence_table_name, self.sequence_pdr_info_table_name)
        self.my_conn.execute_no_fetch(my_sql)

    def del_sequences(self):
        my_sql = """DELETE FROM %s 
                    USING %s 
                    LEFT JOIN %s USING(%s_id) 
                    WHERE %s_id IS NULL;
                """ % (self.sequence_table_name, self.sequence_table_name, self.sequence_table_name, self.sequence_pdr_info_table_name, self.sequence_pdr_info_table_name)
        self.my_conn.execute_no_fetch(my_sql)



    def count_sequence_pdr_info_ill(self):
        results = {}
        primer_suites = self.get_primer_suite_name()
        lane          = self.get_lane().pop()
        for primer_suite in primer_suites:
            primer_suite_lane = primer_suite + ", lane " + lane
            my_sql = """SELECT count(%s_id) 
                        FROM %s 
                          JOIN run_info_ill USING(run_info_ill_id) 
                          JOIN run USING(run_id) 
                          JOIN primer_suite using(primer_suite_id) 
                        WHERE run = '%s' 
                          AND lane = %s
                          AND primer_suite = '%s';
                          """ % (self.sequence_pdr_info_table_name, self.sequence_pdr_info_table_name, self.rundate, lane, primer_suite)
            res    = self.my_conn.execute_fetch_select(my_sql)
            try:
                if (int(res[0][0]) > 0):
                    results[primer_suite_lane] = int(res[0][0])
#                     results.append(int(res[0][0]))
            except Exception:
                self.utils.print_both("Unexpected error from 'count_sequence_pdr_info_ill':", sys.exc_info()[0])
                raise                
        return results
#             int(res[0][0])   
    
    def get_primer_suite_name(self):
        primer_suites = [v.primer_suite for v in self.runobj.samples.itervalues()]
        return list(set(primer_suites))
        
    def get_project_names(self):
        projects = [v.project for v in self.runobj.samples.itervalues()]
        return '", "'.join(set(projects))

    def get_dataset_names(self):
        datasets = [v.dataset for v in self.runobj.samples.itervalues()]
        return '", "'.join(set(datasets))

    def get_lane(self):
        lane = [v.lane for v in self.runobj.samples.itervalues()]
        return set(lane)

    def count_seq_from_file(self):
        try:
            with open(self.unique_file_counts) as fd:
                file_seq_orig = dict(line.strip().split(None, 1) for line in fd)
            file_seq_orig_count = sum([int(x) for x in file_seq_orig.values()])
            return file_seq_orig_count
        except IOError as e:
            self.utils.print_both("Can't open file %s, error = %s" % (self.unique_file_counts, e))         
        except Exception:
            self.utils.print_both("Unexpected error from 'count_seq_from_file':", sys.exc_info()[0])
            raise
        
    def count_seq_from_files_grep(self):
#         grep '>' *-PERFECT_reads.fa.unique
#       or
#         cd /xraid2-2/g454/run_new_pipeline/illumina/20130607/lane_5_A/analysis/reads_overlap/; grep '>' *_MERGED-MAX-MISMATCH-3.unique.nonchimeric.fa | wc -l; date
        try:
            self.suffix_used = list(set([ext for f in self.unique_fasta_files for ext in self.suff_list if f.endswith(ext)]))[0] 
        except:
            print "self.unique_fasta_files = %s, self.suff_list = %s" % (self.unique_fasta_files, self.suff_list)
            self.suffix_used = ""
        print self.suffix_used
        suffix = self.fasta_dir + "/*" + self.suffix_used 
        program_name = "grep"
        call_params  = " '>' " + suffix
        command_line = program_name + call_params
        p1 = Popen(command_line, stdout=PIPE, shell=True)
        p2 = Popen(split("wc -l"), stdin=p1.stdout, stdout=PIPE)
#         output = p2.stdout.read().split(" ")[0].strip()
        output, err = p2.communicate()
#         print output
        return int(output.strip())           


    def check_seq_upload(self):
        file_seq_db_counts   = self.count_sequence_pdr_info_ill()
#        print "file_seq_db_count = %s" % file_seq_db_count
#         file_seq_orig_count = self.count_seq_from_file()
        file_seq_orig_count = self.count_seq_from_files_grep()
        
        for pr_suite, file_seq_db_count in file_seq_db_counts.iteritems():
            if (file_seq_orig_count == file_seq_db_count):
                self.utils.print_both("All sequences from files made it to the db for %s %s: %s == %s\n" % (self.rundate, pr_suite, file_seq_orig_count, file_seq_db_count))
            else:
                self.utils.print_both("Warning: Amount of sequences from files not equal to the one in the db for %s: %s != %s\n" % (pr_suite, file_seq_orig_count, file_seq_db_count))
#                 
#                 ("Oops, amount of sequences from files not equal to the one in the db for %.\nIn file: %s != in db: %s\n==============" % (pr_suite, file_seq_orig_count, file_seq_db_count))
            
    def put_seq_statistics_in_file(self, filename, seq_in_file):
#        if os.path.exists(file_full):
#            os.remove(file_full)
        self.utils.write_seq_frequencies_in_file(self.unique_file_counts, filename, seq_in_file)       
        
    def prepare_taxonomy_upload_query(self, gast_dict):
        # TODO: mv to Taxonomy?
        all_insert_taxonomy_sql_to_run = ""
        self.taxonomy.get_taxonomy_from_gast(gast_dict)
        if (self.db_server == "vamps2"):
            all_insert_taxonomy_sql_to_run = self.taxonomy.insert_split_taxonomy()

        if (self.db_server == "env454"):
            all_insert_taxonomy_sql_to_run = self.taxonomy.insert_whole_taxonomy()
        return all_insert_taxonomy_sql_to_run
        

    def prepare_pdr_info_upload_query(self, fasta, run_info_ill_id, gast_dict):
        all_insert_pdr_info_sql = []

        while fasta.next():
#             all_insert_pdr_info_sql.append(self.insert_pdr_info(fasta, run_info_ill_id))
            all_insert_pdr_info_sql.append(self.insert_pdr_info2(fasta, run_info_ill_id))

        all_insert_pdr_info_sql_all = " ".join(all_insert_pdr_info_sql)
        all_insert_pdr_info_sql_to_run = "BEGIN NOT ATOMIC " + all_insert_pdr_info_sql_all + "END ; "
         
        return all_insert_pdr_info_sql_to_run
    
    def prepare_insert_sequence_uniq_info_ill_sql(self, fasta, gast_dict):
        all_insert_sequence_uniq_info_ill_sql = []
        fasta.reset()
        while fasta.next():
            all_insert_sequence_uniq_info_ill_sql.append(self.insert_sequence_uniq_info_ill(fasta, gast_dict))            
                     
        all_insert_sequence_uniq_info_ill_sql_all = " ".join(list(set(all_insert_sequence_uniq_info_ill_sql)))
        all_insert_sequence_uniq_info_ill_sql_to_run = "BEGIN NOT ATOMIC " + all_insert_sequence_uniq_info_ill_sql_all + "END ; "
        return all_insert_sequence_uniq_info_ill_sql_to_run

class Taxonomy:
    def __init__(self, my_conn):
    
        self.utils        = PipelneUtils()
        self.my_conn      = my_conn
        self.taxa_content = set()
        self.ranks        = ['domain', 'phylum', 'klass', 'order', 'family', 'genus', 'species', 'strain']
        self.taxa_by_rank = []
        self.all_rank_w_id                       = set()
        self.uniqued_taxa_by_rank_dict           = {}
        self.uniqued_taxa_by_rank_w_id_dict      = {}
        self.tax_id_dict                         = {}
        self.taxa_list_w_empty_ranks_dict        = defaultdict(list)
        self.taxa_list_w_empty_ranks_ids_dict    = defaultdict(list)
        self.silva_taxonomy_rank_list_w_ids_dict = defaultdict(list)
        self.silva_taxonomy_ids_dict             = defaultdict(list)
        self.silva_taxonomy_id_per_taxonomy_dict = defaultdict(list)
      
    def get_taxonomy_from_gast(self, gast_dict):
        self.taxa_content = set(v[0] for v in gast_dict.values())

    def get_taxonomy_id_dict(self):
        my_sql = "SELECT %s, %s FROM %s;" % ("taxonomy_id", "taxonomy", "taxonomy")
        res        = self.my_conn.execute_fetch_select(my_sql)
        one_tax_id_dict = dict((y, int(x)) for x, y in res)
        self.tax_id_dict.update(one_tax_id_dict)        
       
    def insert_whole_taxonomy(self):
        all_insert_taxonomy_sql = []   
        for taxonomy in self.taxa_content:
            my_sql = "INSERT IGNORE INTO taxonomy (taxonomy) VALUES ('%s');" % (taxonomy.rstrip())
            all_insert_taxonomy_sql.append(my_sql)
            all_insert_taxonomy_sql_all = " ".join(list(set(all_insert_taxonomy_sql)))
        all_insert_taxonomy_sql_to_run = "BEGIN NOT ATOMIC " + all_insert_taxonomy_sql_all + "END ; "
        return all_insert_taxonomy_sql_to_run
        
    def insert_split_taxonomy(self):
        self.parse_taxonomy()
        self.get_taxa_by_rank()
        self.make_uniqued_taxa_by_rank_dict()
#         if (args.do_not_insert == False):
        self.insert_taxa()
        self.silva_taxonomy
#         if (args.do_not_insert == False):
        self.insert_silva_taxonomy()
        self.get_silva_taxonomy_ids()
        self.make_silva_taxonomy_id_per_taxonomy_dict()
        self.get_all_rank_w_id()
    
    def parse_taxonomy(self):
        self.taxa_list_dict = {taxon_string: taxon_string.split(";") for taxon_string in self.taxa_content}
        self.taxa_list_w_empty_ranks_dict = {taxonomy: tax_list + [""] * (len(self.ranks) - len(tax_list)) for taxonomy, tax_list in self.taxa_list_dict.items()}

    def get_taxa_by_rank(self):
        self.taxa_by_rank = zip(*self.taxa_list_w_empty_ranks_dict.values())
    
    def make_uniqued_taxa_by_rank_dict(self):
        for rank in self.ranks:
            rank_num = self.ranks.index(rank)
        uniqued_taxa_by_rank = set(self.taxa_by_rank[rank_num])
        try:
            self.uniqued_taxa_by_rank_dict[rank] = uniqued_taxa_by_rank
        except:
            raise
    
# self.utils.print_array_w_title(self.uniqued_taxa_by_rank_dict, "self.uniqued_taxa_by_rank_dict made with for")
    
    def insert_taxa(self):
        """
        TODO: make all queries, then insert all? Benchmark!
        """
        for rank, uniqued_taxa_by_rank in self.uniqued_taxa_by_rank_dict.items():
            insert_taxa_vals = '), ('.join(["'%s'" % key for key in uniqued_taxa_by_rank])
    
            shielded_rank_name = self.shield_rank_name(rank)
            rows_affected = self.my_conn.execute_insert(shielded_rank_name, shielded_rank_name, insert_taxa_vals)
            self.utils.print_array_w_title(rows_affected, "rows affected by self.my_conn.execute_insert(%s, %s, insert_taxa_vals)" % (rank, rank))
    
    def shield_rank_name(self, rank):
        return "`"+rank+"`"
    
        """
        >>> obj1 = (6, 1, 2, 6, 3)
        >>> obj2 = list(obj1) #Convert to list
        >>> obj2.append(8)
        >>> print obj2
        [6, 1, 2, 6, 3, 8]
        >>> obj1 = tuple(obj2) #Convert back to tuple
        >>> print obj1
        (6, 1, 2, 6, 3, 8)
        
        """
    
    def get_all_rank_w_id(self):
      all_rank_w_id = self.my_conn.get_all_name_id("rank")
      klass_id = self.utils.find_val_in_nested_list(all_rank_w_id, "klass")
      t = ("class", klass_id[0])
      l = list(all_rank_w_id)
      l.append(t)
      self.all_rank_w_id = set(l)
      # self.utils.print_array_w_title(self.all_rank_w_id, "self.all_rank_w_id from get_all_rank_w_id")
      # (('domain', 78), ('family', 82), ('genus', 83), ('klass', 80), ('NA', 87), ('order', 81), ('phylum', 79), ('species', 84), ('strain', 85), ('superkingdom', 86))
    
    
    def make_uniqued_taxa_by_rank_w_id_dict(self):
      # self.utils.print_array_w_title(self.uniqued_taxa_by_rank_dict, "===\nself.uniqued_taxa_by_rank_dict from def silva_taxonomy")
    
      for rank, uniqued_taxa_by_rank in self.uniqued_taxa_by_rank_dict.items():
        shielded_rank_name = self.shield_rank_name(rank)
        taxa_names         = ', '.join(["'%s'" % key for key in uniqued_taxa_by_rank])
        taxa_w_id          = self.my_conn.get_all_name_id(shielded_rank_name, rank + "_id", shielded_rank_name, 'WHERE %s in (%s)' % (shielded_rank_name, taxa_names))
        self.uniqued_taxa_by_rank_w_id_dict[rank] = taxa_w_id
    
    def insert_silva_taxonomy(self):
    
      # self.utils.print_array_w_title(self.taxa_list_w_empty_ranks_ids_dict.values(), "===\nself.taxa_list_w_empty_ranks_ids_dict from def insert_silva_taxonomy")
    
      field_list = "domain_id, phylum_id, klass_id, order_id, family_id, genus_id, species_id, strain_id"
      all_insert_st_vals = self.utils.make_insert_values(self.taxa_list_w_empty_ranks_ids_dict.values())
      rows_affected = self.my_conn.execute_insert("silva_taxonomy", field_list, all_insert_st_vals)
      self.utils.print_array_w_title(rows_affected, "rows_affected by inserting silva_taxonomy")
    
    def silva_taxonomy(self):
      # silva_taxonomy (domain_id, phylum_id, klass_id, order_id, family_id, genus_id, species_id, strain_id)
      self.make_uniqued_taxa_by_rank_w_id_dict()
      silva_taxonomy_list = []
    
      for taxonomy, tax_list in self.taxa_list_w_empty_ranks_dict.items():
        # ['Bacteria', 'Proteobacteria', 'Deltaproteobacteria', 'Desulfobacterales', 'Nitrospinaceae', 'Nitrospina', '', '']
        silva_taxonomy_sublist = []
        for rank_num, taxon in enumerate(tax_list):
          rank     = self.ranks[rank_num]
          taxon_id = int(self.utils.find_val_in_nested_list(self.uniqued_taxa_by_rank_w_id_dict[rank], taxon)[0])
          silva_taxonomy_sublist.append(taxon_id)
          # self.utils.print_array_w_title(silva_taxonomy_sublist, "===\nsilva_taxonomy_sublist from def silva_taxonomy: ")
        self.taxa_list_w_empty_ranks_ids_dict[taxonomy] = silva_taxonomy_sublist
      # self.utils.print_array_w_title(self.taxa_list_w_empty_ranks_ids_dict, "===\ntaxa_list_w_empty_ranks_ids_dict from def silva_taxonomy: ")
    
    def make_silva_taxonomy_rank_list_w_ids_dict(self):
      for taxonomy, silva_taxonomy_id_list in self.taxa_list_w_empty_ranks_ids_dict.items():
        rank_w_id_list = []
        for rank_num, taxon_id in enumerate(silva_taxonomy_id_list):
          rank = self.ranks[rank_num]
          t = (rank, taxon_id)
          rank_w_id_list.append(t)
    
        self.silva_taxonomy_rank_list_w_ids_dict[taxonomy] = rank_w_id_list
      # self.utils.print_array_w_title(self.silva_taxonomy_rank_list_w_ids_dict, "===\nsilva_taxonomy_rank_list_w_ids_dict from def make_silva_taxonomy_rank_list_w_ids_dict: ")
      """
      {'Bacteria;Proteobacteria;Alphaproteobacteria;Rhizobiales;Rhodobiaceae;Rhodobium': [('domain', 2), ('phylum', 2016066), ('klass', 2085666), ('order', 2252460), ('family', 2293035), ('genus', 2303053), ('species', 1), ('strain', 2148217)], ...
      """
    
    def make_rank_name_id_t_id_str(self, rank_w_id_list):
      a = ""
      for t in rank_w_id_list[:-1]:
        a += t[0] + "_id = " + str(t[1]) + " AND\n"
      a += rank_w_id_list[-1][0] + "_id = " + str(rank_w_id_list[-1][1]) + "\n"
      return a
    
    def make_silva_taxonomy_ids_dict(self, silva_taxonomy_ids):
      for ids in silva_taxonomy_ids:
        self.silva_taxonomy_ids_dict[int(ids[0])] = [int(id) for id in ids[1:]]
      # self.utils.print_array_w_title(self.silva_taxonomy_ids_dict, "===\nsilva_taxonomy_ids_dict from def get_silva_taxonomy_ids: ")
      # {2436595: [2, 2016066, 2085666, 2252460, 2293035, 2303053, 1, 2148217], 2436596: [...
    
    def get_silva_taxonomy_ids(self):
      self.make_silva_taxonomy_rank_list_w_ids_dict()
    
      sql_part = ""
      for taxonomy, rank_w_id_list in self.silva_taxonomy_rank_list_w_ids_dict.items()[:-1]:
        a = self.make_rank_name_id_t_id_str(rank_w_id_list)
        sql_part += "(%s) OR " % a
    
      a_last = self.make_rank_name_id_t_id_str(self.silva_taxonomy_rank_list_w_ids_dict.values()[-1])
      sql_part += "(%s)" % a_last
    
      field_names = "silva_taxonomy_id, domain_id, phylum_id, klass_id, order_id, family_id, genus_id, species_id, strain_id"
      table_name  = "silva_taxonomy"
      where_part  = "WHERE " + sql_part
      silva_taxonomy_ids = self.my_conn.execute_simple_select(field_names, table_name, where_part)
    
      """
      ((2436595L, 2L, 2016066L, 2085666L, 2252460L, 2293035L, 2303053L, 1L, 2148217L), ...
      """
      self.make_silva_taxonomy_ids_dict(silva_taxonomy_ids)
    
    def make_silva_taxonomy_id_per_taxonomy_dict(self):
      for silva_taxonomy_id, st_id_list1 in self.silva_taxonomy_ids_dict.items():
        taxon_string = self.utils.find_key_by_value_in_dict(self.taxa_list_w_empty_ranks_ids_dict.items(), st_id_list1)
        self.silva_taxonomy_id_per_taxonomy_dict[taxon_string[0]] = silva_taxonomy_id
      # self.utils.print_array_w_title(self.silva_taxonomy_id_per_taxonomy_dict, "silva_taxonomy_id_per_taxonomy_dict from silva_taxonomy_info_per_seq = ")
