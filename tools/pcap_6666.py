import struct,sys,collections
f=open(sys.argv[1],'rb'); gh=f.read(24)
le = gh[:4]==b'\xd4\xc3\xb2\xa1'
E='<' if le else '>'
link=struct.unpack(E+'I',gh[20:24])[0]
streams=collections.OrderedDict()
while True:
    h=f.read(16)
    if len(h)<16: break
    ts,tu,cl,ol=struct.unpack(E+'IIII',h); d=f.read(cl)
    off = 20 if link==276 else (16 if link==113 else 14)
    ip=d[off:]
    if not ip or ip[0]>>4!=4 or ip[9]!=6: continue
    ihl=(ip[0]&15)*4; src='.'.join(map(str,ip[12:16])); dst='.'.join(map(str,ip[16:20]))
    tcp=ip[ihl:]; sp,dp,seq=struct.unpack('>HHI',tcp[:8]); doff=(tcp[12]>>4)*4; flags=tcp[13]
    pay=tcp[doff:struct.unpack('>H',ip[2:4])[0]-ihl]
    if 6666 not in (sp,dp): continue
    key=(src,sp,dst,dp)
    s=streams.setdefault(key,{'t0':ts+tu/1e6,'segs':{},'syn':flags&2})
    if pay: s['segs'].setdefault(seq,pay)
for k,s in streams.items():
    data=b''.join(p for _,p in sorted(s['segs'].items()))
    print(k, 't=%.3f'%s['t0'], 'bytes',len(data))
    open('/tmp/s_%s_%d_%s_%d.bin'%k,'wb').write(data)
