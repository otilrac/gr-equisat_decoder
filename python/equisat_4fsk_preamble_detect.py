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

import numpy as np
from gnuradio import gr
import pmt
import array

from equisat_4fsk_block_decode import equisat_4fsk_block_decode

class equisat_4fsk_preamble_detect(gr.basic_block):
    """
    Preamble and frame sync detector and packager for
    Brown Space Engineering's EQUiSat radio using a
    transparent 4FSK protocol.

    Input must be FM or quadrature-demodulated float input, with no
    requirement on the amplitude.

    Note that blocks will only be transmitted when the number of
    symbols equivalent to num_blocks are acquired.

    Allows configuration of max_symbol_ratio, the maximum ratio
    between two subsequent symbols for them to be considered
    equivalent for the purpose of detecting 4-symbol preamble sequences.
    """

    # packet progress states
    ST_WAIT_FOR_PREAMBLE = 0  # searching for preamble or in incomplete preamble
    ST_IN_FRAME_SYNC = 1  # iterating over useless frame sync symbols
    ST_IN_BLOCKS = 2  # waiting to fill block buffer from incoming

    # packet layout constants
    SYMS_PER_BLOCK = equisat_4fsk_block_decode.SYMS_PER_BLOCK
    FRAME_SYNC_LEN = 24  # symbols

    # largest possible/smallest acceptable preamble length (for starting to parse packet)
    MAX_PREAMBLE_LEN = 185  # symbols
    DEF_MIN_PREAMBLE_LEN = 96  # symbols; must be mult of 4

    # maximum number of blocks to read and package after a preamble
    DEF_MAX_NUM_BLOCKS = 150

    # packet/preamble detection constants
    # percentage of first symbol in pair that second must be within to be "the same"
    DEF_MAX_SYMBOL_RATIO = 0.33

    # the maximum buffer to keep unconsumed in case preamble is present
    # should be larger than MAX_PREAMBLE_SIZE or we'll miss preambles
    MAX_UNCONSUMED_SIZE = 2 * MAX_PREAMBLE_LEN

    # normalized threshold for cutoff between +/-3 and +/-1 symbols (where 1.0 is the +3 symbol)
    SYM_SEPERATION_THRESH = 0.667

    def __init__(self, num_blocks=DEF_MAX_NUM_BLOCKS, max_symbol_ratio=DEF_MAX_SYMBOL_RATIO, min_preamble_len=DEF_MIN_PREAMBLE_LEN):
        gr.basic_block.__init__(self,
            name="equisat_4fsk_preamble_detect",
            in_sig=[np.float32],
            out_sig=None)

        self.message_port_register_out(pmt.intern('out'))

        self.num_blocks = num_blocks
        self.max_symbol_ratio = max_symbol_ratio
        self.min_preamble_len = min_preamble_len

        # the current state in the sequence of reading a packet
        self.state = self.ST_WAIT_FOR_PREAMBLE
        # when in ST_IN_FRAME_SYNC, this gives the # of SYMBOLS of frame sync section read so far
        self.frame_sync_syms_read = 0

        # the current input values of the +2 and -2 symbols
        self.high = 0
        self.low = 0

        # buffer to use to transmit message once we get max_num_blocks blocks
        self.blocks_buf = np.zeros(self.SYMS_PER_BLOCK*num_blocks, dtype=np.float32)
        self.blocks_buf_i = 0

        self.reset_state()

    def reset_state(self):
        self.state = self.ST_WAIT_FOR_PREAMBLE
        self.frame_sync_syms_read = 0
        self.blocks_buf[:] = 0
        self.blocks_buf_i = 0
        self.high = 0
        self.low = 0

    def general_work(self, input_items, output_items):
        """ Called by GNU Radio with input stream """
        # NOTE: input_items always includes self.NUM_OLD_DATA "old" bytes
        # we've already read, plus possibly more if we didn't consume them,
        # but the rest are new (see set_history above)
        inpt = input_items[0]

        # finite state machine for different sections of packet
        if self.state is self.ST_WAIT_FOR_PREAMBLE:
            # if searching, check for start of preamble in the HISTORY and
            # set up for start of packet if found
            found, start, end, high, low = self.check_for_preamble(inpt, self.min_preamble_len, self.max_symbol_ratio)

            # if we found a preamble sequence, but it took the whole buffer
            # (i.e. the last preamble sequence was within one sequence of the end)
            # defer and try again next time in case there's more
            # otherwise, continue
            if found and end < len(inpt)-4:
                # setup packet state
                self.high = high
                self.low = low
                # consume the complete preamble
                self.consume(0, end-1)
                # now, try and start reading the frame sync
                self.state = self.ST_IN_FRAME_SYNC

            elif len(inpt) > self.MAX_UNCONSUMED_SIZE:
                # generally, if no preamble was found, wait for more data (don't consume anything)
                # HOWEVER, we don't want that buffer to get too big, so consume anything past the
                # section where a preamble could be
                self.consume(0, len(inpt) - self.MAX_PREAMBLE_LEN)

            return 0

        elif self.state == self.ST_IN_FRAME_SYNC:
            # check if the new data is enough to complete the frame sync
            if len(inpt) >= self.FRAME_SYNC_LEN:
                # move onto blocks, starting past end of frame sync
                self.state = self.ST_IN_BLOCKS
                # consume the frame sync
                self.consume(0, self.FRAME_SYNC_LEN)

            return 0

        elif self.state == self.ST_IN_BLOCKS:
            # copy the input into a buffer to transmit later, not consuming data that overflows that buffer
            blocks_buf_rem = len(self.blocks_buf) - self.blocks_buf_i
            transferred = min(blocks_buf_rem, len(inpt))
            self.blocks_buf[self.blocks_buf_i:self.blocks_buf_i+transferred] = inpt[:transferred]
            self.blocks_buf_i += transferred
            self.consume(0, transferred)

            if self.blocks_buf_i >= len(self.blocks_buf): # should only equal
                # now that we have a full buffer, convert to symbols
                syms = self.get_symbols(self.blocks_buf, high=self.high, low=self.low, sym_seperation_thresh=self.SYM_SEPERATION_THRESH)

                # send message with symbols and reset state
                syms_arr = array.array('B', syms)
                self.message_port_pub(pmt.intern('out'),
                                      pmt.cons(pmt.make_dict(), pmt.init_u8vector(len(syms_arr), syms_arr)))
                self.reset_state()

            return 0

        else:  # revert
            assert False

    @staticmethod
    def check_for_preamble(inpt, min_preamble_len=DEF_MIN_PREAMBLE_LEN,
                           sym_sim_thresh=DEF_MAX_SYMBOL_RATIO):
        """ Checks for a run of sets of 4 adjacent symbols resembling
        a preamble "cycle", i.e. -2 -2 +2 +2. Returns True if such a
        run of min_preamble_len symbols exists (min_preamble_len/4 such cycles).
        Returns whether one was found, its start and end index
        cycle, and the low and high value.
        """
        found_first = False
        start = -1
        end = -1
        high_sum = 0
        low_sum = 0
        cycle_count = 0
        i = 0
        while i < len(inpt) - 4:
            if equisat_4fsk_preamble_detect._is_preamble_cycle(inpt, i, sym_sim_thresh):
                # (note start if first found)
                if not found_first:
                    start = i
                # add cycle and then jump to next
                cycle_count += 1
                # the low part comes first in the cycle (is_preamble_cycle enforces this)
                low_sum += inpt[i] + inpt[i + 1]
                high_sum += inpt[i + 2] + inpt[i + 3]
                i += 4
                found_first = True
                # in case we're the end, use this cycle as the end
                # was incremented past last cycle, plus one to be start of next byte sequence (i.e. the frame sync)
                end = i

            elif found_first:
                # if we didn't find a cycle but we'd already found one,
                # we've reached the end of _that_ possible preamble,
                # so check if it's a suitable preamble
                if 4 * cycle_count < min_preamble_len:  # num symbols
                    # no valid preamble if insufficient cycles found,
                    # so reset and keep looking
                    found_first = False
                    start = -1
                    end = -1
                    high_sum = 0
                    low_sum = 0
                    cycle_count = 0

                else:
                    # otherwise, return this preamble
                    break

            else:
                # if we found nothing, continue stepping one at a time
                i += 1

        if 4 * cycle_count < min_preamble_len:  # num symbols
            # no valid preamble if insufficient cycles found
            return False, -1, -1, 0, 0
        else:
            # average ALL the +2s and -2s to get the high/low values
            # (two symbols per cycle)
            high = high_sum / (2 * cycle_count)
            low = low_sum / (2 * cycle_count)
            return True, start, end, high, low

    @staticmethod
    def _is_preamble_cycle(inpt, i, sym_sim_thresh):
        """ Checks if the set of 4 raw values in inpt starting at i
        resemble a preamble cycle up to sim_thresh """
        pair1_close = abs(inpt[i] - inpt[i + 1]) <= sym_sim_thresh * abs(inpt[i])
        pair2_close = abs(inpt[i + 2] - inpt[i + 3]) <= sym_sim_thresh * abs(inpt[i + 2])
        pair1_avg = (inpt[i] + inpt[i + 1]) / 2
        pair2_avg = (inpt[i + 2] + inpt[i + 3]) / 2
        return pair1_close and pair2_close and pair1_avg < 0 and pair2_avg > 0

    @staticmethod
    def get_symbols(inpt, high, low, sym_seperation_thresh=SYM_SEPERATION_THRESH):
        """ Converts raw input values in a numpy array into numerical base-4 symbols,
        based on the given high value corresponding to +2 deviation and low to -2
        """
        # shift symbols from range [high, low] to range [1, -1]
        # and then threshold
        syms = 2 * (inpt - low) / float(high - low) - 1
        for i in range(len(syms)):
            if syms[i] >= sym_seperation_thresh:
                syms[i] = 1
            elif syms[i] >= 0.0:
                syms[i] = 0
            elif syms[i] > -sym_seperation_thresh:
                syms[i] = 2
            else:
                syms[i] = 3
        return syms.astype(np.uint8)