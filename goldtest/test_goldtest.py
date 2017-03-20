import unittest

import goldtest


class TestGoldtest(goldtest.TestCase):
    def test_simple(self):
        gt = goldtest.Goldtest(self)
        inp = gt.load('input')
        output = [x * 2 for x in inp]
        output.append(100)
        gt.simple_test(output)
        output[-1] = 'hi'
        gt.simple_test(output)

    def test_failure(self):
        gt = goldtest.Goldtest(self)
        inp = gt.load('input')
        failing_gold = gt.load('failing_gold')
        diff_output = gt.diff(failing_gold, inp)
        gt.simple_test(diff_output)


if __name__ == '__main__':
    unittest.main()
