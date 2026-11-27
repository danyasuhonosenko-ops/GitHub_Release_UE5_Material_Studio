#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Compiled Binary Module: run_job.py (v2.1.1)
STUDIO_VERSION = "v2.1.1"
def _r(_g):
    import sys as _s, builtins as _bi, zlib as _z, base64 as _b, hashlib as _h
    
    if _s.gettrace() is not None or getattr(_bi.exec, "__name__", "") != "exec" or getattr(_bi.compile, "__name__", "") != "compile":
        raise RuntimeError('Integrity check failed')
    _dk = _h.pbkdf2_hmac("sha256", b"DAL_PBR_STUDIO_2026_CORE_V2", bytes.fromhex("601c7d8626e10be3d6f16d4c5b660e7e"), 12000, dklen=32)
    _d = _b.b85decode('dqE?X@E32fGC9Wm4zP{0$)>Qct@V%IX?21yBC~Fbaaqu^A@>o5QX1c@B5J7-P4#yt&}_th;5eEPq-)miFkO%n(DL{nGK8!g`UDP4F8bp0!^m-*t}71rvEsf4njpT3U-95RDukIcB9wq1)ohRsM}>;J5hw5-F?r0$>|pS<@gR;dd8ufd3X@W~Y(stWuHZ~XwD#l6t6uovQNJ_0_ca`?ES!$^?SVd75cH(GBQ#}1ShcA)ssMJ}UmkG3m%+hN8fTv^PJ|C?()hXQ-;!lJ+KUr+CZou<Lh$Tq&Tt9xg1}2H`+9?oyYJz0&Q2@jx72)}Wc(^vtU$_;SQ(47!NV;h-*-+M`vv6joqd?RCMgZ9IxM{LlkwD!>1Q+%z0r8F0@fMf@c0B1`s9j`y3^eeMhErO?DU{%`v1=R&zYn71Fmd@){@i78^<L|-Gl#X@gCE>VE{!#qkma~LKzjY<2Ft>X3ucYxmh!jx~yh(`yCGtfNMDMiOF|Q#za|!hW3ZQmhZfA64Pj{+$h9xx}0Ut+5LB2>zyv`wX?1^k@8I&&*6q<Y$Qc1Z#YnoJ^LZ-T5kJLk{vu@K}%JBiM~qs?2CZ!kp$enx<p}qwm1_rsLf2Yy(2oBW56@8(ii5l*ODYX-IUCkuu)dF6^Z7SJqZv$*)LSU8&~5h!OeWolE6(dn0ESlb7VBABvE)Y2|i}WEpc^f@TaC};6>=kJgbPf2!b#K#b+FYtywXY%O~RI1#3u#qRn)~^q|byO*^A)0s9Xb5=#ptlC{J~Yf$;j2ChvQoSC`#AxllnQ=SoCl*u`$#7DeN;rzF+_XE~$4-m)lEavg+da=e{qjVrDHWaY*9db&??X^HPjRg%l=@5N*g4IdYW_o-DwQRb>elnC-U8vT1(n`sLey6C!^l))i|IP^h6908#ZM{^^iW;uHDFp4+{DH)USE1Vdv7<s@w!S4{G7X0IKnPa|A9-7#Mpwp6+w=B%Mzyv2z1|Xcs@sksZs8%$%~O!HEM8<^@$~pv$!o~85)hZu0e9&M@Sj3Q_}BYM@D5>H^aI8Kqkb#pOdmMJc&_qlBs&x9v!?;zh=<dzNfa%Q6mT^d-$3)s&$DfENfy%VL#-Rjj>r|E8o=xPyp%nl$VhG25z8Lvl4)S@G;X->{y=lmL4!9a!t3efaC`${h=L*(3HUfw!K{A)af6i_PxLdxmLEiNdc0;1{UpJI%v%qR3+&c{L9G^h=}5$JF)<$(?M`CQa^=3KVLJP!>muyVq=>3mrW2UTxH}?)a~&1|+c*$!`<u9IY;7mV!?v_mCt!LJ6L3j7hCKaQd(8`yhNmx=4YY=5o%FT')
    _ks = bytearray()
    _i = 0
    while len(_ks) < len(_d):
        _ks.extend(_h.sha512(_dk + _i.to_bytes(4, "little")).digest())
        _i += 1
    _c = _z.decompress(bytes(v ^ _ks[j] for j, v in enumerate(_d)))
    _bi.exec(_bi.compile(_c, "<run_job.py_compiled>", "exec"), _g)
_r(globals())
del _r
