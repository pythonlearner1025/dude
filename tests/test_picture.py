from m8py.picture import DIGITS, mark, png, base64
from PIL import Image
from io import BytesIO

def test_digit_bitmaps_match_reference():assert DIGITS[0]==(7,5,5,5,7) and DIGITS[8]==(7,5,7,5,7)
def test_disc_and_digit_placement():
    rgb=bytearray([100]*40*40*3); mark(rgb,40,40,[{"id":1,"x":.5,"y":.5}]); at=lambda x,y:tuple(rgb[(y*40+x)*3:(y*40+x)*3+3])
    assert at(20,5)==(255,255,255); assert at(12,20)==(30,30,30); assert at(20,13)==(255,255,255)
def test_png_roundtrip():
    rgb=bytes([1,2,3]*12); encoded=png(rgb,4,3); image=Image.open(BytesIO(encoded)); assert image.size==(4,3) and image.tobytes()==rgb and base64(encoded).startswith("iVBOR")
