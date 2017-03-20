import inspect
import os
import string
import random
import json
import difflib
from decimal import Decimal
import errno
import unittest
from db import get_db_data
from json import JSONEncoder

TEST_PREFIX = 'test_'


class Goldtest(object):

    """Each thread must have its own Goldtest instance"""

    def __init__(self, testobj, db_metadata=None, db_engine=None):
        self.wildcard = Wildcard()
        filepath = inspect.getfile(testobj.__class__)
        directory = os.path.dirname(os.path.realpath(filepath))
        self.testobj = testobj
        test_name = testobj._testMethodName
        if test_name.startswith(TEST_PREFIX):
            test_name = test_name[len(TEST_PREFIX):]
        else:
            assert False, 'WEIRD: %s does not start with "%s"' % (
                test_name, TEST_PREFIX)
        self.test_name = test_name
        class_name = testobj.__class__.__name__
        self.gold_dir = os.path.join(directory, 'golds', class_name, test_name)

        self.engine = None
        self.metadata = None
        if db_engine and db_metadata:
            self.engine = db_engine
            self.metadata = db_metadata

    def simple_test(self, output):
        self.test('output', output)

    def path(self, name):
        return os.path.join(self.gold_dir, name + '.json')

    def load(self, name):
        with open(self.path(name)) as f:
            return self.decode(f.read())

    def decode(self, s):
        if s and s[0] != '[' and s[0] != '{':
            # this is not json, just return the string
            # TODO(vadim): need to parse floats/ints, because people use
            # invalid JSON where the entire string is one of the valid value
            # types, but not an object or array
            return s

        sentinel = find_wildcard_sentinel(s)
        s_with_sentinel = s.replace('"\\*"', '"' + sentinel + '"')
        obj = json.loads(s_with_sentinel)
        return recursive_replace(obj, obj, sentinel, self.wildcard)

    # json encodes o (json-serializable thing that contains wildcards) into a str
    def encode(self, o):
        # for simple strings, just return the string (to avoid weird escaping
        # for simple outputs)
        if isinstance(o, str):
            return o

        self.wildcard.sentinel = ''
        serialized = json.dumps(o, cls=CustomEncoder)
        self.wildcard.sentinel = find_wildcard_sentinel(serialized)
        dump = json.dumps(o, cls=CustomEncoder, indent=4, sort_keys=True)
        return dump.replace('"' + self.wildcard.sentinel + '"', '"\\*"') + '\n'

    def test_db(self, test_name, tables=None):
        data = get_db_data(self.metadata, self.engine, tables=tables)
        for table_name, data in data.iteritems():
            gold_name = os.path.join(test_name, table_name)
            self.test(gold_name, data)

    def test(self, test_name, obj):
        gold_path = os.path.join(self.gold_dir, test_name + '.json')

        if _gen_run == 1:
            mkdir_p(os.path.dirname(gold_path))
            with open(gold_path, 'w') as f:
                f.write(self.encode(obj))
            return
        if _gen_run == 2:
            with open(gold_path) as f:
                round1 = self.decode(f.read())

            # if already matching, don't do any wildcarding
            if not self.diff(round1, obj):
                return

            def pre(gold, obj):
                if isinstance(gold, (str, unicode, float, int)):
                    if gold != obj:
                        return self.wildcard
            wildcarded = visit(round1, obj, pre, None)
            with open(gold_path, 'w') as f:
                f.write(self.encode(wildcarded))
            return

        with open(gold_path) as f:
            gold = self.decode(f.read())
        diff = self.diff(gold, obj)
        if diff:
            msg = '\nDifference found in %s\n' % gold_path
            self.testobj.fail(msg + diff)

    def diff(self, gold, obj):
        gold_str = self.encode(gold)
        obj_wildcarded = self._wildcard_similar(gold, obj)
        obj_str = self.encode(obj_wildcarded)
        if obj_str == gold_str:
            return None

        diffs = difflib.unified_diff(gold_str.split('\n'),
                                     obj_str.split('\n'),
                                     n=1e9)

        return process_diff(diffs)

    # replaces items in obj with wildcard if the corresponding item in gold is a
    # wildcard
    def _wildcard_similar(self, gold, obj):
        return recursive_replace(gold, obj, self.wildcard, self.wildcard)


def process_diff(diffs):
    """
    returns a string with the difflib diff special chars replaced by something
    more meaningful
    """

    lines = []
    saw_at = False
    last_prefix = None
    for d in diffs:
        first, rest = d[0], d[1:]

        # strip out everything before the actual diff begins
        if not saw_at and first != '@':
            continue
        if not saw_at:
            saw_at = True
            continue

        # change prefixes to something meaningful
        if first == '-':
            prefix = 'exp:'
        elif first == '+':
            prefix = 'got:'
        else:
            prefix = '    '

        # make diffs easier to read by not showing the same prefix over and over
        if prefix == last_prefix and prefix.strip():
            prefix = '   :'
        else:
            last_prefix = prefix

        lines.append(prefix + rest)

    return '\n'.join(lines)


def recursive_replace(gold, obj, search_for, replace_with):
    """
    Replaces values in `obj` with `replace_with` if the corresponding value
    in `gold` == `search_for`
    """
    def pre(gold, obj):
        return replace_with if gold == search_for else None
    return visit(gold, obj, pre, None)


def visit(gold, obj, pre_func, post_func):
    if pre_func:
        pre = pre_func(gold, obj)
        if pre is not None:
            return pre

    if isinstance(obj, (list, tuple)) and isinstance(gold, (list, tuple)):
        i = 0
        for g, o in zip(gold, obj):
            obj[i] = visit(g, o, pre_func, post_func)
            i += 1
    elif isinstance(obj, dict) and isinstance(gold, dict):
        for k, v in gold.iteritems():
            if k in obj:
                obj[k] = visit(v, obj[k], pre_func, post_func)

    if post_func:
        post = post_func(gold, obj)
        if post is not None:
            return post

    return obj


def random_string(n):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(n))


def find_wildcard_sentinel(s):
    """returns a string that is not in the input string"""
    n = 10
    while True:
        sentinel = 'WILDCARD_' + random_string(n)
        if sentinel not in s:
            return sentinel
        n += 10  # make collision a kazillion times less likely :)


class CustomEncoder(JSONEncoder):

    def default(self, o):
        if isinstance(o, Wildcard):
            return o.sentinel
        elif isinstance(o, Decimal):
            return str(o)
        return JSONEncoder.default(self, o)


class Wildcard(object):

    def __init__(self):
        # you should never see this sentinel value
        self.sentinel = 'SOMETHING_IS_BROKEN'

_gen_run = 0


class TestCase(unittest.TestCase):
    def run(self, *args, **kwargs):
        if not os.getenv('GOLDTEST_GEN'):
            return unittest.TestCase.run(self, *args, **kwargs)

        global _gen_run

        # initial generation run
        _gen_run = 1
        unittest.TestCase.run(self, *args, **kwargs)

        # wildcarding generation run
        _gen_run = 2
        unittest.TestCase.run(self, *args, **kwargs)


def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc:  # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise


def main():
    class Dummy(object):
        _testMethodName = 'test_dummy'
    gt = Goldtest(Dummy())
    x = {'yo': gt.wildcard, 'asdf': [1, 2, gt.wildcard], 'lol': gt.wildcard, 'k': [1]}
    y = {'yo': 234234, 'asdf': [3, 2, 'hi'], 'lol': [1, 2, 3], 'k': {'g': 3}}
    enc = gt.encode(x)
    print '-' * 30
    print enc
    print '-' * 30
    enc2 = gt.encode(gt.decode(enc))
    print enc2
    print '-' * 30
    print enc == enc2
    print '-' * 30

    print gt.diff(x, y)

if __name__ == '__main__':
    main()
