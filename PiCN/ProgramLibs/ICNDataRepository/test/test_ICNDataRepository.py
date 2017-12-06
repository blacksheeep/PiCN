"""Test the ICN Data Repository using fetch"""

import os
import shutil
import unittest
from random import randint

from PiCN.ProgramLibs.Fetch import Fetch

from PiCN.Packets import Name
from PiCN.ProgramLibs.ICNDataRepository import ICNDataRepository


class test_ICNDataRepository(unittest.TestCase):

    def setUp(self):
        self.data1 = "data1"
        self.data2 = 'A' * 5000
        self.data3 = 'B' * 20000

        self.path = "/tmp/repo_unit_test"
        try:
            os.stat(self.path)
        except:
            os.mkdir(self.path)
        with open(self.path + "/f1", 'w+') as content_file:
            content_file.write(self.data1)
        with open(self.path + "/f2", 'w+') as content_file:
            content_file.write(self.data2)
        with open(self.path + "/f3", 'w+') as content_file:
            content_file.write('B' * 20000)

        self.portoffset = randint(0,999)
        self.ICNRepo: ICNDataRepository = ICNDataRepository("/tmp/repo_unit_test", "/test/data", 9000 + self.portoffset)
        self.fetch = Fetch("127.0.0.1", 9000 + self.portoffset)

    def tearDown(self):
        try:
            shutil.rmtree(self.path)
            os.remove("/tmp/repo_unit_test")
        except:
            pass
        self.ICNRepo.stop_repo()
        self.fetch.stop_fetch()

    def test_fetch_single_data(self):
        """Test fetching a single data object without chunking"""
        self.ICNRepo.start_repo()
        content = self.fetch.fetch_data(Name("/test/data/f1"))
        self.assertEqual(content, self.data1)

    def test_fetch_small_data(self):
        """Test fetching a small data object with little chunking"""
        self.ICNRepo.start_repo()
        content = self.fetch.fetch_data(Name("/test/data/f2"))
        self.assertEqual(content, self.data2)

    def test_fetch_big_data(self):
        """Test fetching a big data object with lot of chunking"""
        self.ICNRepo.start_repo()
        content = self.fetch.fetch_data(Name("/test/data/f3"))
        self.assertEqual(content, self.data3)

    def test_fetch_nack(self):
        """Test fetching content which is not available and get nack"""
        self.ICNRepo.start_repo()
        content = self.fetch.fetch_data(Name("/test/data/f4"))
        self.assertEqual(content, "Received Nack: No Matching Content")
