'''
Created on 08.04.2011

@author: joe
'''

import time
from cloudfusion.store.store import *
import logging
from cloudfusion.util.exponential_retry import retry
from cloudfusion.mylogging import db_logging_thread
import tempfile
from cloudfusion.store.webdav.cadaver_client import CadaverWebDAVClient

class WebdavStore(Store):
    def __init__(self, config):
        super(WebdavStore, self).__init__()
        self.name = 'webdav'
        self._logging_handler = self.name
        self.logger = logging.getLogger(self._logging_handler)
        self.logger = db_logging_thread.make_logger_multiprocessingsave(self.logger)
        self.logger.info("creating %s store", self.name)
        self.client = CadaverWebDAVClient(config['url'], config['user'], config['password'] )
        self.logger.info("api initialized")
        
    def __deepcopy__(self, memo):
        from copy import deepcopy
        cls = self.__class__
        result = cls.__new__(cls)
        memo[id(self)] = result
        for k, v in self.__dict__.items():
            if k == 'logger':
                setattr(result, k, self.logger)
            elif k == '_logging_handler':
                setattr(result, k, self._logging_handler)
            else:
                setattr(result, k, deepcopy(v, memo))
        return result
        
    def get_name(self):
        self.logger.info("getting name")
        return self.name
    
    @retry((Exception), tries=14, delay=0.1, backoff=2)
    def get_file(self, path_to_file): 
        self.logger.debug("getting file: %s", path_to_file)
        self._raise_error_if_invalid_path(path_to_file)
        with tempfile.NamedTemporaryFile(delete=False) as f:
            tempfile_path = f.name
        self._webdav_cmd('get', path_to_file[1:], tempfile_path) # cut first / from path
        with open(tempfile_path) as f:
            ret = f.read()
        os.remove(tempfile_path)
        return ret 
        
    def __get_size(self, fileobject):
        pos = fileobject.tell()
        fileobject.seek(0,2)
        size = fileobject.tell()
        fileobject.seek(pos, 0)
        return size
    
    @retry((Exception), tries=1, delay=0) 
    def store_fileobject(self, fileobject, path, interrupt_event=None):
        size = self.__get_size(fileobject)
        self.logger.debug("Storing file object of size %s to %s", size, path)
        if hasattr(fileobject, 'name'):
            file_name = fileobject.name
        else:
            with tempfile.NamedTemporaryFile(delete=False) as fh:
                for line in fileobject:
                    fh.write(line)
                fh.flush()
                file_name = fh.name
        self.client.upload(file_name, path)
        return int(time.time())
    
    
    # worst case: object still exists and takes up space or is appended to, by mistake
    # with caching_store, the entry in cache is deleted anyways 
    @retry((Exception), tries=5, delay=0) 
    def delete(self, path, is_dir=False): #is_dir parameter does not matter to dropbox
        self.logger.debug("deleting %s", path)
        self._raise_error_if_invalid_path(path)
        if is_dir:
            self.client.rmdir(path)
        else:
            self.client.rm(path)
        
    @retry((Exception))
    def account_info(self):
        self.logger.debug("retrieving account info")
        return "Webdav "

    @retry((Exception))
    def create_directory(self, directory):
        self.logger.debug("creating directory %s", directory)
        self.client.mkdir(directory)
        
    def duplicate(self, path_to_src, path_to_dest):
        self.logger.debug("duplicating %s to %s", path_to_src, path_to_dest)
        self.client.move(path_to_src, path_to_dest)
    
    def move(self, path_to_src, path_to_dest):
        self.logger.debug("moving %s to %s", path_to_src, path_to_dest)
        self.client.move(path_to_src, path_to_dest)
    
    def get_overall_space(self):
        self.logger.debug("retrieving all space") 
        return self.client.get_overall_space()

    def get_used_space(self):
        self.logger.debug("retrieving used space")
        return self.client.get_used_space()
        
    #@retry((Exception))
    def get_directory_listing(self, directory):
        self.logger.debug("getting directory listing for %s", directory)
        return self.client.get_directory_listing(directory)
    
    def _handle_error(self, error, method_name, remaining_tries, *args, **kwargs):
        if isinstance(error, NoSuchFilesytemObjectError):
            self.logger.error("Error could not be handled: %s", error)
            raise error # do not retry (error cannot be handled)
        if remaining_tries == 0: # throw error after last try 
            raise StoreAccessError(str(error), 0) 
        return False
        
    #@retry((Exception))
    def _get_metadata(self, path):
        self.logger.debug("getting metadata for %s", path)
        self._raise_error_if_invalid_path(path)
        if path == "/": # workaraund for root metadata
            ret = {}
            ret["bytes"] = 0
            ret["modified"] = time.time()
            ret["path"] = "/"
            ret["is_dir"] = True
            return ret
        return self.client._get_metadata(path)
        
    def _get_time_difference(self):
        self.logger.debug("getting time difference")
        return 0
    
    def get_logging_handler(self):
        return self._logging_handler
    
    def get_max_filesize(self):
        """Return maximum number of bytes per file"""
        return 1000*1000*1000*1000