import os
import random

WORDS = {}
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'adjectives.list')) as f:
    WORDS['adjectives'] = f.readlines()
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nouns.list')) as f:
    WORDS['nouns'] = f.readlines()
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'verbs.list')) as f:
    WORDS['verbs'] = f.readlines()


def get_verb() -> str:
    return random.choice(WORDS['verbs']).strip()


def get_noun() -> str:
    return random.choice(WORDS['nouns']).strip()


def get_adjective() -> str:
    return random.choice(WORDS['adjectives']).strip()
