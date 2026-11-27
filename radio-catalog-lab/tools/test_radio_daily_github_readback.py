"""Synthetic GitHub responses derived from actual Git objects."""
import base64
import unittest

import test_radio_daily_git_lab_transport as fixture
from radio_daily_git_lab_transport import REF, ZERO, snapshot
from radio_daily_github_transfer_contract import DESTINATION
from radio_daily_github_readback import GitHubReadback, API


class GitHubReadbackTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.GitLabTransportTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.head=self.f.bootstrap()["commit"]
        self.git=self.f.transport
        self.override={}
        self.calls=[]
        self.reader=GitHubReadback(self.read)

    def read(self,url,limit):
        self.calls.append(url)
        self.assertTrue(url.startswith(API+"/git/"))
        path=url.removeprefix(API)
        if path in self.override:
            return self.override[path]
        if path.startswith("/git/ref/"):
            return 200,dict(ref=REF,object=dict(type="commit",sha=self.head))
        oid=path.rsplit("/",1)[-1]
        if path.startswith("/git/commits/"):
            tree=self.git._git("rev-parse",oid+"^{tree}").decode().strip()
            return 200,dict(sha=oid,tree=dict(sha=tree))
        if path.startswith("/git/trees/"):
            entries=[]
            for row in self.git._git("ls-tree","-l","-z",oid).split(b"\0"):
                if not row:
                    continue
                metadata,name=row.split(b"\t",1)
                mode,kind,sha,size=metadata.decode().split()
                item=dict(path=name.decode(),mode=mode,type=kind,sha=sha)
                if kind=="blob":
                    item["size"]=int(size)
                entries.append(item)
            return 200,dict(sha=oid,truncated=False,tree=entries)
        data=self.git._git("cat-file","blob",oid)
        return 200,dict(sha=oid,size=len(data),encoding="base64",
                        content=base64.encodebytes(data).decode())

    def test_verified_readback_of_actual_git_snapshot(self):
        self.assertEqual(self.reader.read_head(DESTINATION,REF),self.head)
        self.assertEqual(self.reader.read_tree(DESTINATION,self.head),snapshot(self.f.f.store,8))

    def test_wrong_ref_and_repository_refused_without_calls(self):
        with self.assertRaisesRegex(ValueError,"unauthorized"):
            self.reader.read_head(DESTINATION,"refs/heads/main")
        with self.assertRaisesRegex(ValueError,"unauthorized"):
            self.reader.read_tree("https://github.com/other/repo.git",self.head)
        self.assertFalse(self.calls)

    def test_only_404_means_absent_ref(self):
        path="/git/ref/"+REF.removeprefix("refs/")
        self.override[path]=(404,{})
        self.assertEqual(self.reader.read_head(DESTINATION,REF),ZERO)
        self.override[path]=(403,{})
        with self.assertRaisesRegex(ValueError,"unavailable"):
            self.reader.read_head(DESTINATION,REF)

    def test_corrupted_blob_refused(self):
        self.reader.read_tree(DESTINATION,self.head)
        path=next(url.removeprefix(API) for url in self.calls if "/git/blobs/" in url)
        _,blob=self.read(API+path,10000000)
        blob["content"]=base64.b64encode(b"x"*blob["size"]).decode()
        self.override[path]=(200,blob)
        with self.assertRaisesRegex(ValueError,"blob hash"):
            self.reader.read_tree(DESTINATION,self.head)

    def test_truncated_tree_refused(self):
        path="/git/trees/"+self.git._git("rev-parse",self.head+"^{tree}").decode().strip()
        _,doc=self.read(API+path,10000000)
        doc["truncated"]=True
        self.override[path]=(200,doc)
        with self.assertRaisesRegex(ValueError,"incomplete"):
            self.reader.read_tree(DESTINATION,self.head)

    def test_omitted_tree_entry_refused_by_hash(self):
        path="/git/trees/"+self.git._git("rev-parse",self.head+"^{tree}").decode().strip()
        _,doc=self.read(API+path,10000000)
        doc["tree"].pop()
        self.override[path]=(200,doc)
        with self.assertRaisesRegex(ValueError,"tree hash"):
            self.reader.read_tree(DESTINATION,self.head)
