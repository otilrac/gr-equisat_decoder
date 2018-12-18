#!/usr/bin/env python
# -*- coding: utf-8 -*-
# 
# Copyright 2018 <+YOU OR YOUR COMPANY+>.
# 
# This is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.
# 
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this software; see the file COPYING.  If not, write to
# the Free Software Foundation, Inc., 51 Franklin Street,
# Boston, MA 02110-1301, USA.
# 

from gnuradio import gr, gr_unittest
from xdl_micro_4fsk_preamble_detect import xdl_micro_4fsk_preamble_detect
import qa_xdl_micro_4fsk_block_decode
import numpy as np

packet_raw_EQUiSatx50 = qa_xdl_micro_4fsk_block_decode.packet_raw_EQUiSatx50

class qa_xdl_micro_4fsk_preamble_detect (gr_unittest.TestCase):

    def setUp (self):
        self.tb = gr.top_block ()

    def tearDown (self):
        self.tb = None

    def test_is_preamble_cycle(self):
        self.assertFalse(xdl_micro_4fsk_preamble_detect._is_preamble_cycle([0, 0, 0, 0], 0, 0.1))
        self.assertTrue(xdl_micro_4fsk_preamble_detect._is_preamble_cycle([-1, -1, 1, 1], 0, 0.1))
        self.assertTrue(xdl_micro_4fsk_preamble_detect._is_preamble_cycle([-1000, -900, 100, 101], 0, 0.1))
        self.assertFalse(xdl_micro_4fsk_preamble_detect._is_preamble_cycle([-1000, -900, 900, 1000], 0, 0.01))
        self.assertFalse(xdl_micro_4fsk_preamble_detect._is_preamble_cycle([-1000, -900, 900, 1000], 0, 0.1))

    def test_check_for_preamble(self):
        found, start, end, high, low = xdl_micro_4fsk_preamble_detect.check_for_preamble(
            [0, 0.1, -0.1, -1, -1, 1, 1, -1, -1, 1, 1, -1, -1, 1, 1, 1, 0, -1], 12, 0.1)
        self.assertTrue(found)
        self.assertEqual(start, 3)
        self.assertEqual(end, 15)
        self.assertEqual(high, 1)
        self.assertEqual(low, -1)

        inpt = np.array(packet_raw_EQUiSatx50)
        found, start, end, high, low = xdl_micro_4fsk_preamble_detect.check_for_preamble(inpt)
        self.assertTrue(found)
        self.assertEqual(start, 9)
        self.assertEqual(end, 193)
        self.assertAlmostEqual(high, 9200, delta=100)
        self.assertAlmostEqual(low, -9500, delta=100)

        # TODO: test multiple preambles, with bad ones initially

    def test_get_symbols(self):
        # note: +2 = 1, +1 = 0, -1 = 2, -2 = 3
        high = 200 # avg +1 = 104 => +1 cutoff = 152.5
        low = -180 # avg -1 = -85 => -1 cutoff = -132.5
        inpt = np.array([-173, 212, 30, -60, 153, -300, -132, -132.6, 20])
        exp_syms = [3, 1, 0, 2, 1, 3, 2, 3, 0]
        syms = xdl_micro_4fsk_preamble_detect.get_symbols(inpt, high, low)
        self.assertFloatTuplesAlmostEqual(syms, exp_syms)


if __name__ == '__main__':
    gr_unittest.run(qa_xdl_micro_4fsk_preamble_detect, "qa_xdl_micro_4fsk_preamble_detect.xml")
