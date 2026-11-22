import struct,sys
f=open(sys.argv[1],'rb'); gh=f.read(24); link=struct.unpack('<I',gh[20:24])[0]
segs={}; isn=None
while True:
    h=f.read(16)
    if len(h)<16: break
    _,_,cl,_=struct.unpack('<IIII',h); d=f.read(cl)
    ip=d[20 if link==276 else 16:]
    if not ip or ip[0]>>4!=4 or ip[9]!=6: continue
    ihl=(ip[0]&15)*4; tcp=ip[ihl:]; sp,dp,seq=struct.unpack('>HHI',tcp[:8])
    if sp!=6666: continue
    if tcp[13]&2: isn=seq+1; continue
    pay=tcp[(tcp[12]>>4)*4:struct.unpack('>H',ip[2:4])[0]-ihl]
    if pay: segs.setdefault(seq,pay)
rel=sorted(((s-isn)%2**32,p) for s,p in segs.items())
buf=bytearray(); pos=0; gaps=0
for r,p in rel:
    if r>pos: gaps+=1; break
    if r+len(p)>pos: buf+=p[pos-r:]; pos=r+len(p)
print('contiguous bytes',len(buf),'stopped at gap' if gaps else 'complete')
i=0; out=open(sys.argv[2],'wb'); types={}
while i+4<=len(buf):
    L=struct.unpack('<I',buf[i:i+4])[0]
    if L<4 or i+L>len(buf): break
    p=buf[i+4:i+L]; i+=L
    if p[0]==1:
        st=p[3]; types[st]=types.get(st,0)+1
        if st==0x20: out.write(p[12:])
print('stream subtypes',{hex(k):v for k,v in types.items()})
