# Claude · 2026-11-22 · Session 8e680ddd-6b26-44d7-8b07-e667fe163a25 · Google Flights link builder (the tfs value)
"""Builds Google Flights URLs without the (dead) ?q= form.

  search_url('2027-03-12', ['SEA'], ['BOS', 'PVD'])                one-way economy search, all airlines, several airports
  booking_url('2027-03-12', ['SEA'], ['BOS'], legs=[('SEA','2027-03-12','MDW','WN','7111'), ('MDW','2027-03-12','BOS','WN','7222')])
                                                                    the booking-options page for one exact itinerary

The tfs value is a protobuf, base64url encoded. Field numbers follow what Google's own URLs carry
(Info: 3 flight data, 8 passenger, 9 seat, 19 trip; FlightData: 2 date, 4 chosen flight legs, 13 from, 14 to;
airport: 1 kind, 2 code; leg: 1 from, 2 date, 3 to, 5 airline code, 6 flight number). Tested in Chrome Nov 22 2026.
"""
import base64, sys

def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F; n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n: return bytes(out)
def _key(field, wire): return _varint(field << 3 | wire)
def _vi(field, n): return _key(field, 0) + _varint(n)
def _ld(field, data): data = data.encode() if isinstance(data, str) else data; return _key(field, 2) + _varint(len(data)) + data
def _airport(code): return _vi(1, 1) + _ld(2, code)

def _tfs(date, origins, dests, legs=None, seat=1, adults=1, max_stops=None):
    fd = _ld(2, date)
    for leg in legs or []:
        frm, d, to, al, num = leg
        fd += _ld(4, _ld(1, frm) + _ld(2, d) + _ld(3, to) + _ld(5, al) + _ld(6, str(num)))
    if max_stops is not None: fd += _vi(5, max_stops)
    for o in origins: fd += _ld(13, _airport(o))
    for d in dests: fd += _ld(14, _airport(d))
    info = _vi(1, 28) + _vi(2, 2) + _ld(3, fd) + b''.join(_vi(8, 1) for _ in range(adults)) + _vi(9, seat) + _vi(14, 1) + _vi(19, 2)
    return base64.urlsafe_b64encode(info).decode().rstrip('=')

def search_url(date, origins, dests, **kw):
    return 'https://www.google.com/travel/flights/search?tfs=' + _tfs(date, origins, dests, **kw) + '&hl=en&gl=us&curr=USD'

def booking_url(date, origins, dests, legs, **kw):
    return 'https://www.google.com/travel/flights/booking?tfs=' + _tfs(date, origins, dests, legs=legs, **kw) + '&hl=en&gl=us&curr=USD'

if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) >= 3: print(search_url(a[0], a[1].split(','), a[2].split(',')))
    else: print(search_url('2027-03-12', ['SEA'], ['BOS', 'PVD']))
