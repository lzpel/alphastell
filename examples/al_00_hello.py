#!/usr/bin/env python3
"""stellarator (rust, pyo3) の hello() を python から呼ぶ最小例 (issue #5)。
"""

from alphastell import hello, hello_constructor, hello_numpy
import numpy as np

hello()

hello_numpy(np.array([1, 2, 3])) # print "Hello, stellarator!" to stdout

a=hello_constructor(name="stellarator")

a.say_hello() # print "Hello, stellarator!" to stdout