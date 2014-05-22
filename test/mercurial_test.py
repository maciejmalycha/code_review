import os
import os.path
import shutil

from proboscis import test
from proboscis.asserts import assert_equal, assert_true
from dingus import patch, Dingus

from sandbox import REPO_MASTER, config

import flask.templating
from app import app, db
from db_create import db_create

from test.mercurial import MercurialBase



@test
class MercurialTest(MercurialBase):

    def login(self, username, password):
        return self.app.post('/login', data=dict(
            email=username,
            password=password
        ), follow_redirects=True)

    def logout(self):
        return self.app.get('/logout', follow_redirects=True)

    # Disable docstring printing
    def shortDescription(self):
        return None

    def setUp(self):
        if os.path.exists(REPO_MASTER):
            shutil.rmtree(REPO_MASTER)
        if os.path.exists(config.REPO_PATH):
            shutil.rmtree(config.REPO_PATH)
        db_create()
        self.app = app.test_client()
        self.init_repos()
        self.commit_master("Initial creation",   tag="root")
        self.commit_master("IWD 8.0 root",       tag="b800",        rev="root")
        self.commit_master("IWD 8.0.001 branch", bmk="iwd-8.0.001", rev="b800")
        self.commit_master("IWD 8.0.002 root",   tag="b801",        rev="b800")
        self.commit_master("IWD 8.0.002 branch", bmk="iwd-8.0.002", rev="b801")
        self.commit_master("IWD 8.0.003 branch", bmk="iwd-8.0.003", rev="b801")
        self.commit_master("IWD 8.5.000 root",   tag="b810",        rev="root")
        self.commit_master("IWD 8.1 root",       tag="b811",        rev="b810")
        self.commit_master("IWD 8.1.000 branch", bmk="iwd-8.1.000", rev="b811")
        self.commit_master("IWD 8.1.001 branch", bmk="iwd-8.1.001", rev="b811")
        self.commit_master("IWD 8.1.101 branch", bmk="iwd-8.1.101", rev="b811")
        self.commit_master("IWD 8.5.000 branch", bmk="iwd-8.5.000", rev="b810")
        self.slave.hg_pull()

    def tearDown(self):
        db.drop_all()

    def test_recognize_reworks(self):
        """Push chain of two commits and one commit, both lines originating
           from active changeset
            - Verify, that both are qualified as reworks
            - Choose one and create changeset
            - Verify, that other one is moved to 'New'
        """
        # Commit new revision IWD-0005 on top of iwd-8.0.003
        rev = self.commit_master("IWD-0005: Reworks parent", bmk="IWD-0005",
                                 rev="iwd-8.0.003")
        parent_node = self.master.revision(rev).node
        # Login into Detektyw
        rv = self.login("maciej.malycha@genesyslab.com", "password")
        assert_true("Active changes" in rv.data)
        # Open new review
        # TODO: sha1 -> node
        rv = self.app.post("/changes/new", data={"action": "start",
                                                 "sha1": parent_node})
        # Commit new revision and chain of two revisions on top of IWD-0005
        self.commit_master("IWD-0005: Rework 1.0", bmk="rev1")
        self.commit_master("IWD-0005: Rework 1.1")
        self.commit_master("IWD-0005: Rework 2.0", bmk="rev2", rev="IWD-0005")
        # Verify, that they don't show up as new changes
        with patch("flask.templating._render", Dingus(return_value='')):
            rv = self.app.get("/changes/new")
            revisions = flask.templating._render.calls[0].args[1]['revisions']
        assert_equal(len(revisions), 0)
        # But show up as reworks
        with patch("flask.templating._render", Dingus(return_value='')):
            rv = self.app.get("/review/1")
            revisions = flask.templating._render.calls[0].args[1]['descendants']
        assert_equal(len(revisions), 2)
        assert_equal(revisions[0].title, "IWD-0005: Rework 2.0")
        assert_equal(revisions[1].title, "IWD-0005: Rework 1.1")
        # Create new changeset out of one revision
        rv = self.app.post("/review/1", data={"action": "rework",
                                              "sha1": revisions[1].node})
        # Verify, that second one is not rework candidate
        #TODO: Check if full chain of revisions is sent to collaborator
        with patch("flask.templating._render", Dingus(return_value='')):
            rv = self.app.get("/review/1")
            revisions = flask.templating._render.calls[0].args[1]['descendants']
        assert_equal(len(revisions), 0)
        # But new revision
        with patch("flask.templating._render", Dingus(return_value='')):
            rv = self.app.get("/changes/new")
            revisions = flask.templating._render.calls[0].args[1]['revisions']
        assert_equal(len(revisions), 1)
        assert_equal(revisions[0].title, "IWD-0005: Rework 2.0")
        # Abandon this revision to clean up
        rv = self.app.post("/changes/new", data={"action": "abandon",
                                                 "sha1": revisions[0].node})

    def test_revision_from_old_changeset(self):
        """Push revision originating from older changeset
            - Verify, that it appears on 'New'
            - Abandon active changeset
            - Verify, that commit becomes rework candidate
        """
        # Commit new revision IWD-0006 on top of iwd-8.1.001
        self.commit_master("IWD-0006: Older changeset", bmk="IWD-0006",
                           rev="iwd-8.1.001")
        # Login into Detektyw
        rv = self.login("maciej.malycha@genesyslab.com", "password")
        assert_true("Active changes" in rv.data)
        # Verify, that IWD-0006 revision is on list of new revisions
        with patch("flask.templating._render", Dingus(return_value='')):
            rv = self.app.get("/changes/new")
            revisions = flask.templating._render.calls[0].args[1]['revisions']
        assert_equal(len(revisions), 1)
        assert_true(revisions[0].title.startswith("IWD-0006"))
        review_sha1 = revisions[0].node
        # Open new review
        rv = self.app.post("/changes/new", data={"action": "start",
                                                 "sha1": review_sha1})
        # Commit new revision on top of IWD-0006
        self.commit_master("IWD-0006: Newer changeset")
        # Verify, that it shows up as rework
        with patch("flask.templating._render", Dingus(return_value='')):
            rv = self.app.get("/review/1")
            revisions = flask.templating._render.calls[0].args[1]['descendants']
        assert_equal(len(revisions), 1)
        assert_equal(revisions[0].title, "IWD-0006: Newer changeset")
        rework_sha1 = revisions[0].node
        # Make it changeset
        rv = self.app.post("/review/1", data={"action": "rework",
                                              "sha1": rework_sha1})
        # Commit new revision on top of older changeset
        self.commit_master("IWD-0006: Side branch", rev=review_sha1)
        # Verify, that it is on list of new revisions
        with patch("flask.templating._render", Dingus(return_value='')):
            rv = self.app.get("/changes/new")
            revisions = flask.templating._render.calls[0].args[1]['revisions']
        assert_equal(len(revisions), 1)
        assert_equal(revisions[0].title, "IWD-0006: Side branch")
        # But not on the review list
        with patch("flask.templating._render", Dingus(return_value='')):
            rv = self.app.get("/review/1")
            revisions = flask.templating._render.calls[0].args[1]['descendants']
        assert_equal(len(revisions), 0)
        # Abandon active changeset
        self.app.post("/review/1", data={"action": "abandon_changeset",
                                         "sha1": rework_sha1})
        # Verify, that side branch is not on new
        with patch("flask.templating._render", Dingus(return_value='')):
            rv = self.app.get("/changes/new")
            revisions = flask.templating._render.calls[0].args[1]['revisions']
        assert_equal(len(revisions), 0)
        # But listed as rework
        with patch("flask.templating._render", Dingus(return_value='')):
            rv = self.app.get("/review/1")
            revisions = flask.templating._render.calls[0].args[1]['descendants']
        assert_equal(len(revisions), 1)
        assert_equal(revisions[0].title, "IWD-0006: Side branch")

    def test_dangling_heads(self):
        """Merge review with dangling heads
            - Verify, that last active review is merged
            - Verify, that dangling heads became new
            - Verify, that heads no longer appear as rework candidates
        """
        # Commit new revision IWD-0009 on top of iwd-8.5.000
        self.commit_master("IWD-0009: Dangling branches root", bmk="IWD-0009",
                           rev="iwd-8.5.000")
        # Login into Detektyw
        rv = self.login("maciej.malycha@genesyslab.com", "password")
        assert_true("Active changes" in rv.data)
        # Verify, that IWD-0009 revision is on list of new revisions
        with patch("flask.templating._render", Dingus(return_value='')):
            rv = self.app.get("/changes/new")
            revisions = flask.templating._render.calls[0].args[1]['revisions']
        assert_equal(len(revisions), 1)
        assert_true(revisions[0].title.startswith("IWD-0009"))
        review_sha1 = revisions[0].node
        # Open new review
        rv = self.app.post("/changes/new", data={"action": "start",
                                                 "sha1": review_sha1})
        # Commit two rework branches to IWD-0009
        self.commit_master("IWD-0009: Rework 1.0", bmk="rev1")
        self.commit_master("IWD-0009: Rework 1.1")
        self.commit_master("IWD-0009: Rework 2.0", bmk="rev2", rev="IWD-0009")
        # Verify, that they don't show up as new changes
        with patch("flask.templating._render", Dingus(return_value='')):
            rv = self.app.get("/changes/new")
            revisions = flask.templating._render.calls[0].args[1]['revisions']
        assert_equal(len(revisions), 0)
        # But show up as reworks
        with patch("flask.templating._render", Dingus(return_value='')):
            rv = self.app.get("/review/1")
            revisions = flask.templating._render.calls[0].args[1]['descendants']
        assert_equal(len(revisions), 2)
        # Merge IWD-0009 but not the reworks
        # TODO: Review should be merged, not changeset
        rv = self.app.post("/merge", data={"sha1": review_sha1})
        # Verify, that reworks show up on new
        with patch("flask.templating._render", Dingus(return_value='')):
            rv = self.app.get("/changes/new")
            revisions = flask.templating._render.calls[0].args[1]['revisions']
        assert_equal(len(revisions), 2)
        assert_equal(revisions[0].title, "IWD-0009: Rework 2.0")
        assert_equal(revisions[1].title, "IWD-0009: Rework 1.1")
        # But not on the review page
        with patch("flask.templating._render", Dingus(return_value='')):
            rv = self.app.get("/review/1")
            revisions = flask.templating._render.calls[0].args[1]['descendants']
        assert_equal(len(revisions), 0)

    def test_diverged_merge(self):
        """Merge review with conflicting changes (diverged)
            - Verify, that merge is not done
            - Verify, that local repository is recovered
            - Verify, that user is informed
        """
        # Commit two new revisions IWD-0010 on top of iwd-8.0.002
        rev1 = self.commit_master("IWD-1010: Diverged merge 1", bmk="IWD-1010",
                                  rev="iwd-8.0.002")
        rev1_node = self.master.revision(rev1).node
        rev2 = self.commit_master("IWD-2010: Diverged merge 2", bmk="IWD-2010",
                                  rev="iwd-8.0.002")
        rev2_node = self.master.revision(rev2).node
        # Login into Detektyw
        rv = self.login("maciej.malycha@genesyslab.com", "password")
        assert_true("Active changes" in rv.data)
        # Open review for first revision and merge it
        rv = self.app.post("/changes/new", data={"action": "start",
                                                 "sha1": rev1_node})
        self.app.post("/merge", data={"sha1": rev1_node})
        # Open review for second revision and try to merge it
        rv = self.app.post("/changes/new", data={"action": "start",
                                                 "sha1": rev2_node})
        rv = self.app.post("/merge", data={"sha1": rev2_node},
                           follow_redirects=True)
        # Verify, that user is informed
        assert_true("There is merge conflict. Merge with bookmark "
                    "iwd-8.0.002 and try again." in rv.data)
        # Verify, that merge is not done
        assert_true("iwd-8.0.002" in self.master.revision(rev1_node).bookmarks)
        assert_true("iwd-8.0.002" in self.slave.revision(rev1_node).bookmarks)
        with patch("flask.templating._render", Dingus(return_value='')):
            rv = self.app.get("/review/2")
            review = flask.templating._render.calls[0].args[1]['review']
        assert_equal(review.status, "ACTIVE")
        # Verify, that repository has recovered
        for key, value in self.slave.hg_status().items():
            assert_equal(value, [])
        assert_equal(self.slave.hg_id(), "000000000000")

    def test_merge_with_ancestor(self):
        """Merge review with official branch being descendant of active
           changeset (merging with ancestor case)
            - Verify, that official branch is not recognized as rework
            - Verify, that merge is correctly done
        """
        # Commit new revision IWD-0012 on top of iwd-8.1.101
        rev = self.commit_master("IWD-0012: Merge with ancestor",
                                 bmk="IWD-0012", rev="iwd-8.1.101")
        parent_node = self.master.revision(rev).node
        # Login into Detektyw
        rv = self.login("maciej.malycha@genesyslab.com", "password")
        assert_true("Active changes" in rv.data)
        # Open new review
        rv = self.app.post("/changes/new", data={"action": "start",
                                                 "sha1": parent_node})
        # Add new commit and move official branch there
        rev = self.commit_master("IWD-0012: Descendant being official branch",
                                 bmk="iwd-8.1.101")
        child_node = self.master.revision(rev).node
        # Verify, that official branch is not recognized as rework
        with patch("flask.templating._render", Dingus(return_value='')):
            rv = self.app.get("/review/1")
            revisions = flask.templating._render.calls[0].args[1]['descendants']
        assert_equal(len(revisions), 0)
        # And can be merged without problem
        rv = self.app.post("/merge", data={"sha1": parent_node})
        # Review is merged
        with patch("flask.templating._render", Dingus(return_value='')):
            rv = self.app.get("/review/1")
            review = flask.templating._render.calls[0].args[1]['review']
        assert_equal(review.status, "MERGED")
        # And official bookmark didn't move
        child_revision = self.master.revision(child_node)
        assert_true("iwd-8.1.101" in child_revision.bookmarks)


def run_tests():
    from proboscis import TestProgram
    TestProgram().run_and_exit()

if __name__ == "__main__":
    run_tests()
