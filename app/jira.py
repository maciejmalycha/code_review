from __future__ import absolute_import

from jira import JIRA, JIRAError
import re
import logging
import warnings
from app.crypto import decryption
from app import app
from app.model import Changeset, Review, User


logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", "A true SSLContext object is not available.")

def token_search(commit):
    """ Search for tokens (IWD-XXXX, EVO-XXXX, IAP-XXXX) in commit """
    IWD = re.findall(r'[iI][wW][dD]-[0-9]{1,}', commit)
    EVO = re.findall(r'[eE][vV][oO]-[0-9]{1,}', commit)
    IAP = re.findall(r'[iI][aA][pP]-[0-9]{1,}', commit)
    return IWD + EVO + IAP
    
def comment_added(sha1, comments):
    """ Search for sha1 in comments """
    for comment in comments:
        comment = comment.body
        if (sha1 in comment) and ('Code delivered by' in comment) and ('Branch:' in comment):
            return True
    return False


def jira_comment(jira, issue_num, author, date, project, branch,
                                link_hgweb, link_detektyw, commit_msg):
    """ Add comment to single relevant JIRA ticket """
    
    issue = jira.issue(issue_num)
    
    comment = 'Code delivered by *{author}* on {date}.\n'.format(author=author.encode('utf8'), date=date)
    comment += 'Branch: {project}/{branch}\n'.format(project=project.encode('utf8'), branch=branch.encode('utf8'))
    comment += 'Commit: {link_hgweb}\n'.format(link_hgweb=link_hgweb)
    comment += 'Inspection: http://pl-byd-srv01.emea.int.genesyslab.com/ci/review/{link_detektyw}\n'.format(link_detektyw=link_detektyw)
    comment += 'Commit message:\n{noformat}'
    comment += '\n{commit_msg}\n'.format(commit_msg=commit_msg.encode('utf8'))
    comment += '{noformat}\n'
    
    jira.add_comment(issue, comment)
    logger.info('Added comment to {issue}'.format(issue=issue_num))

def jira_integrate(changeset, user):
    """ Add comment to all relevant JIRA tickets """
    
    jira = JIRA(options={'server': 'https://jira.genesys.com'}, basic_auth=(user.jira_login, decryption(user.jira_password)))
    link_hgweb_static = app.config["HG_PROD"] + "/rev/"
    for token in token_search(changeset.title):
        link_hgweb = link_hgweb_static + changeset.sha1
        jira_comment(jira, token, changeset.owner, changeset.created_date, 'IWD', 
                        changeset.review.target, link_hgweb, changeset.review_id, changeset.title)

def integrate_all_old(jira_login, enc_jira_password):
    """ Add comment to all relevant historical JIRA tickets """
    
    jira = JIRA(options={'server': 'https://jira.genesys.com'}, basic_auth=(jira_login, decryption(enc_jira_password)))
    link_hgweb_static = app.config["HG_PROD"] + "/rev/"
    
    reviews = Review.query.filter(Review.status == "MERGED").all()
    
    
    for review in reviews:
        changeset = review.changesets[0]
        for token in token_search(changeset.title):
            try:
                issue = jira.issue(token)
                if not comment_added(changeset.sha1, issue.fields.comment.comments):
                    link_hgweb = link_hgweb_static + changeset.sha1
                    jira_comment(jira, token, changeset.owner, changeset.created_date, 'IWD', 
                                    changeset.review.target, link_hgweb, changeset.review_id, changeset.title)
            except JIRAError as e:
                if e.status_code == 404:
                    print "Issue does not exist (url: {url})".format(url=e.url)
