"""Any 8+ character piece of a credential is redacted — head, tail, middle —
in one pass over the text, however long the credential (agy review of 0.6.4).
"""

import random
import string
import time
import unittest

from gentar.redaction import scrubber


def token(n, seed=7):
    rnd = random.Random(seed)
    return "".join(rnd.choice(string.ascii_letters + string.digits) for _ in range(n))


class PiecesTest(unittest.TestCase):

    def test_a_middle_slice_is_redacted(self):
        # a value longer than a window, cut at both ends, leaves its middle
        secret = token(900)
        middle = secret[300:700]
        out = scrubber([("JWT", secret)])(f"log: …{middle}… end")
        self.assertNotIn(middle[:20], out)
        self.assertNotIn(middle[-20:], out)
        self.assertIn("«redacted:JWT»", out)
        self.assertTrue(out.startswith("log: …") and out.endswith("… end"), out)

    def test_head_and_tail_still_redacted(self):
        secret = token(40)
        s = scrubber([("TOKEN", secret)])
        for piece in (secret[:9], secret[-9:], secret[5:25]):
            self.assertNotIn(piece, s(f"x {piece} y"), piece)

    def test_a_short_accidental_overlap_is_left_alone(self):
        secret = token(40)
        s = scrubber([("TOKEN", secret)])
        seven = secret[10:17]                       # below the 8-char floor
        self.assertIn(seven, s(f"x {seven} y"))

    def test_a_long_credential_scrubs_in_linear_time(self):
        secret = token(5000)
        text = ("line of ordinary output 0123456789\n" * 3000) + secret[1000:1400]
        s = scrubber([("JWT", secret)])
        t0 = time.monotonic()
        out = s(text)
        took = time.monotonic() - t0
        self.assertNotIn(secret[1000:1020], out)
        self.assertLess(took, 2.0, f"scrub took {took:.2f}s")


if __name__ == "__main__":
    unittest.main()
