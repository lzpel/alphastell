#!/usr/bin/env python3
"""stellarator (rust, pyo3) の hello() を python から呼ぶ最小例 (issue #5)。
"""

from stellarator import hello, hello_constructor

hello()

a=hello_constructor(name="stellarator")

a.say_hello() # print "Hello, stellarator!" to stdout