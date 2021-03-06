import multiprocessing
import argparse
import re
import sys
import logging
from datetime import datetime
import hashlib
import gzip
import requests
import os
import json
import time
from splunk_http_event_collector import http_event_collector
from helpers.certparser import process_cert
from helpers.hostparser import proccess_host
import random

def process_hosts_file(file_queue, key, hostlist=['localhost'], index='sonarsslhost', sourcetype='sonarsslhost', batchsize=16384, useesid=False):
    logger = logging.getLogger('SSLImporter')
    while True:
        host = random.choice(hostlist)
        print host
        hec = http_event_collector(key, host)
        gzfilename = file_queue.get()
        if gzfilename == "DONE":
            return True
        logger.warning("Loading file {f} at {d}".format(f=gzfilename, d=datetime.now()))
        with gzip.open(gzfilename, 'rb') as resultsfile:
            m = re.search('.*\/(\d{8})', gzfilename)
            if m:
                filedate = m.group(1)
            else:
                m = re.search('.*\/(\d{4}-\d{2}-\d{2})', gzfilename)
                filedate = m.group(1)
                filedate = re.sub('-', '', filedate, 0, 0)
            filedate_struct = time.strptime(filedate, "%Y%m%d")
            filedate_epoch = time.mktime(filedate_struct)
            batchcount = 0
            for line in resultsfile:
                cleanline = line.strip('\n')
                (host, certhash) = cleanline.split(',', 1)
                newhost = {}
                newhost['host'] = host
                newhost['hash'] = certhash
                newhost['seen'] = filedate
                newhost['seen_epoch'] = filedate_epoch
                if useesid:
                    cert_hash = hashlib.sha1(newhost['host']+newhost['hash']+'sonar')
                    newhost['id'] = cert_hash.hexdigest()
                newhost = proccess_host(newhost, logger)
                payload = {}
                payload.update({"index":index})
                payload.update({"host":host})
                payload.update({"sourcetype":sourcetype})
                payload.update({"source":gzfilename})
                payload.update({"event":newhost})
                hec.batchEvent(payload)
                batchcount = batchcount + 1
                if batchcount == batchsize:
                    hec.flushBatch()
                    batchcount = 0
            if batchcount > 0:
                hec.flushBatch()

def main(argv):
    logger = logging.getLogger('SSLImporter')
    logger_format = logging.Formatter('\033[1;32m%(levelname)-5s %(module)s:%(funcName)s():%(lineno)d %(asctime)s\033[0m| '
                                  '%(message)s')
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logger_format)
    logger.addHandler(stream_handler)

    DEFAULT_DOWNLOAD_PATH = u'/sonar/sonar.ssl'
    DEFAULT_POOLSIZE = 1
    DEFAULT_SPLUNK_HOST = u'127.0.0.1'
    DEFAULT_SPLUNK_INDEX = "sonarsslhost"
    DEFAULT_SPLUNK_SOURCETYPE = "sonarsslhost"

    parser = argparse.ArgumentParser()   
    parser.add_argument('--downloadpath', default=DEFAULT_DOWNLOAD_PATH,
                        help=u'Location to read downloaded files. (default {0})'.format(DEFAULT_DOWNLOAD_PATH)) 
    parser.add_argument('--poolsize', default=DEFAULT_POOLSIZE, 
                        help=u'Number of processes to spawn. (default: {0})'.format(DEFAULT_POOLSIZE))
    parser.add_argument('--hec_key', default='', 
                        help=u'Splunk HTTP Event Collector(HEC) token. (default: <blank>)')
    parser.add_argument('--splunk_indexer', default=DEFAULT_SPLUNK_HOST, 
                        help=u'Splunk indexer or load balancer. (default: {})'.format(DEFAULT_SPLUNK_HOST))
    parser.add_argument('--splunk_index', default=DEFAULT_SPLUNK_INDEX, 
                        help=u'Splunk index. (default: {})'.format(DEFAULT_SPLUNK_INDEX))
    parser.add_argument('--splunk_sourcetype', default=DEFAULT_SPLUNK_SOURCETYPE, 
                        help=u'Splunk sourcetype. (default: {})'.format(DEFAULT_SPLUNK_SOURCETYPE))
    args = parser.parse_args(argv[1:])

    numproc = int(args.poolsize)

    directory=args.downloadpath
    http_event_collector_key = args.hec_key

    file_queue = multiprocessing.Queue()
    pool = multiprocessing.Pool(numproc, process_hosts_file,(file_queue, args.hec_key,[args.splunk_indexer], args.splunk_index, args.splunk_sourcetype,))

    for filename in os.listdir(directory):
        if filename.endswith("hosts.gz"):
            file_queue.put(os.path.join(directory,filename))

    for i in range(numproc):
        file_queue.put("DONE")

    pool.close()
    pool.join()

if __name__ == '__main__':
    main(sys.argv)
