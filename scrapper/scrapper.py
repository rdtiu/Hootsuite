import datetime
import json
import logging
import time

import praw

from mongoengine import connect
from mongoengine.errors import ValidationError

import settings

from models import Submission, Comment


class Scrapper(object):
    def __init__(self, interval=None):
        self.mongo_client = self.create_mongo_connection()
        self.reddit = self.create_praw_connection()
        self.subreddits = self.read_subreddits()
        self.last_read = None
        # default 1 hour in seconds if not specified
        self.interval = interval or 60 * 60 * 1

    @staticmethod
    def create_praw_connection():
        reddit = praw.Reddit(client_id=settings.client_id,
                             client_secret=settings.client_secret,
                             user_agent=settings.user_agent,
                             username=settings.username,
                             password=settings.password)
        return reddit

    @staticmethod
    def create_mongo_connection():
        mongo_client = connect(settings.database_name,
                               host=settings.database_host,
                               port=settings.database_port)
        return mongo_client

    @staticmethod
    def read_subreddits():
        listing = open(settings.subreddits_filename).read()
        listing = json.loads(listing)
        children = listing['data']['children']
        subreddits = [child['data']['display_name'] for child in children]
        return subreddits

    @staticmethod
    def interval_timestamp(now, then):
        return time.mktime(then.timetuple()), time.mktime(now.timetuple())

    def run(self):
        while True:
            now = datetime.datetime.now()
            if self.last_read is None:
                self.last_read = now
                self.read_subreddits_content(now, self.last_read)

            if (now - self.last_read).total_seconds() > self.interval:
                self.read_subreddits_content(now, self.last_read)
                self.last_read = now

    def read_subreddits_content(self, now, then):
        for subreddit in self.subreddits:
            self.read_subreddit_submissions(subreddit, now, then)
        logging.info('Subreddits processed at timestamp: ' + str(now))

    def read_subreddit_submissions(self, subreddit_name, now, then):
        subreddit = self.reddit.subreddit(subreddit_name)
        for submission in subreddit.submissions(*self.interval_timestamp(now, then)):
            try:
                self.submission_save(submission.id,
                                     subreddit_name,
                                     submission.title,
                                     submission.created_utc)
            except ValidationError:
                logging.debug(
                    'Key: ' + submission.id + '\n' +
                    'Subreddit name: ' + str(len(subreddit_name)) + '\n'
                    'Title length: ' + str(len(submission.title))
                )
                continue
            except Exception as exc:
                logging.debug(exc.message)
                continue
            self.read_submission_comments(submission, subreddit_name)

    def read_submission_comments(self, submission, subreddit_name):
        submission.comment_sort = 'new'
        all_comments = submission.comments.list()
        for comment in all_comments:
            try:
                self.comment_save(comment.id, subreddit_name, comment.body, comment.created_utc)
            except ValidationError:
                logging.debug(
                    'Key: ' + comment.id + '\n' +
                    'Subreddit name: ' + str(len(subreddit_name)) + '\n'
                    'Body length: ' + str(len(comment.body))
                )
                continue
            except Exception as exc:
                logging.debug(exc.message)
                continue
            self.read_comment_replies(comment, subreddit_name)

    def read_comment_replies(self, comment, subreddit_name):
        comment_forest = comment.replies
        result = comment_forest.replace_more()
        while result:
            result = comment_forest.replace_more()

        for reply_comment in comment_forest.list():
            try:
                self.comment_save(reply_comment.id,
                                  subreddit_name,
                                  reply_comment.body,
                                  reply_comment.created_utc)
            except ValidationError:
                logging.debug(
                    'Key: ' + reply_comment.id + '\n' +
                    'Subreddit name: ' + str(len(subreddit_name)) + '\n'
                    'Body length: ' + str(len(reply_comment.body))
                )
                continue
            except Exception as exc:
                logging.debug(exc.message)
                continue

    @staticmethod
    def submission_save(submission_id, subreddit_name,
                        submission_title, submission_timestamp):

        Submission(submission_id, subreddit_name,
                   submission_title, submission_timestamp).save()

    @staticmethod
    def comment_save(comment_id, subreddit_name,
                     comment_body, comment_timestamp):

        Comment(comment_id, subreddit_name,
                comment_body, comment_timestamp).save()


def main():
    logging.basicConfig(filename=settings.logging_filename, level=logging.DEBUG)
    scrapper = Scrapper(interval=settings.interval)
    scrapper.run()

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        logging.debug(exc.message)
        main()
