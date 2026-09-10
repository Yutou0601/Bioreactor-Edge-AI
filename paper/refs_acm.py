
# -*- coding: utf-8 -*-
"""refs.bib → ACM Reference Format 的書目條目。

為什麼從 .bib 重建而不是改寫現成的 Springer 字串：Springer 樣式
（`Surname, I.I.: Title. Journal Vol(No), pp (Year)`）與 ACM 樣式
（`Surname, F. M. Year. Title. Journal Vol, No, pp.`）在**欄位順序**上
不同——年份要從句尾搬到作者後面。用正則去搬順序，遇到題名含句點、
或作者姓氏含逗號時就會錯。.bib 有結構化欄位，直接照欄位排才可靠。

⚠ 鍵序一律沿用 main.tex 的 thebibliography：內文的 [n] 是照那個順序
  編號的，這裡若自行重排會與內文對不上。ACM 要求依字母排序，而
  thebibliography 本來就是字母序，兩者一致。

模板 §3.5 與 §7 的格式（逐字對照其範例）：
  期刊  Bowman, M., Debray, S. K., and Peterson, L. L. 1993.
        Reasoning about naming systems. ACM Trans. Program. Lang.
        Syst. 15, 5 (Nov. 1993), 795-825. DOI= http://...
  會議  Fröhlich, B. and Plate, J. 2000. The cubic mouse: ...
        In Proceedings of the SIGCHI Conference ... 526-531.
刊名與會議名為斜體，其餘為正體，故回傳 (文字, 是否斜體) 的片段串列。
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
BIB = os.path.join(HERE, 'refs.bib')

# LaTeX 重音 → Unicode。兩種寫法都要吃：\'{a} 與 {\'a}。
ACCENT = {
    "'": {'a': '\u00e1', 'e': '\u00e9', 'i': '\u00ed', 'o': '\u00f3',
          'u': '\u00fa', 'c': '\u0107', 'n': '\u0144', 's': '\u015b',
          'z': '\u017a', 'y': '\u00fd',
          'A': '\u00c1', 'E': '\u00c9', 'I': '\u00cd', 'O': '\u00d3',
          'U': '\u00da'},
    '`': {'a': '\u00e0', 'e': '\u00e8', 'i': '\u00ec', 'o': '\u00f2',
          'u': '\u00f9', 'A': '\u00c0', 'E': '\u00c8', 'O': '\u00d2'},
    '"': {'a': '\u00e4', 'e': '\u00eb', 'i': '\u00ef', 'o': '\u00f6',
          'u': '\u00fc', 'y': '\u00ff',
          'A': '\u00c4', 'O': '\u00d6', 'U': '\u00dc'},
    '^': {'a': '\u00e2', 'e': '\u00ea', 'i': '\u00ee', 'o': '\u00f4',
          'u': '\u00fb', 'A': '\u00c2', 'E': '\u00ca', 'O': '\u00d4'},
    '~': {'a': '\u00e3', 'n': '\u00f1', 'o': '\u00f5',
          'A': '\u00c3', 'N': '\u00d1', 'O': '\u00d5'},
    'v': {'c': '\u010d', 's': '\u0161', 'z': '\u017e', 'r': '\u0159',
          'e': '\u011b', 'n': '\u0148', 'd': '\u010f', 't': '\u0165',
          'C': '\u010c', 'S': '\u0160', 'Z': '\u017d'},
    'u': {'g': '\u011f', 'a': '\u0103', 'G': '\u011e'},
    'c': {'c': '\u00e7', 's': '\u015f', 'C': '\u00c7', 'S': '\u015e'},
    '=': {'a': '\u0101', 'e': '\u0113', 'o': '\u014d', 'u': '\u016b'},
    '.': {'z': '\u017c', 'e': '\u0117'},
}


def delatex(s):
    """去除 LaTeX 重音與保護括號。⚠ 先處理重音再拆括號，
    否則 {\\'a} 的括號被拆掉之後 \\'a 會黏上鄰字。"""
    def rep(m):
        cmd, ch = m.group(1), m.group(2)
        return ACCENT.get(cmd, {}).get(ch, ch)

    # \'{a} 與 \v{s}
    s = re.sub(r'\\([\'`"^~vuc=.])\{(\w)\}', rep, s)
    # {\'a}
    s = re.sub(r'\{\\([\'`"^~vuc=.])\s*(\w)\}', rep, s)
    # \'a（無括號）
    s = re.sub(r'\\([\'`"^~])(\w)', rep, s)
    s = s.replace('\\&', '&').replace('\\%', '%').replace('\\_', '_')
    s = s.replace('{', '').replace('}', '')
    # LaTeX 連字：--- 為破折號、-- 為連接號。不轉的話題名會印出
    # 「oxidation--reduction」這種原始碼。頁碼另行處理，不走這裡。
    s = s.replace('---', '—').replace('--', '–')
    return re.sub(r'\s+', ' ', s).strip()


def parse_bib(path=BIB):
    """本檔是自家維護的 .bib，格式固定，不引入 bibtexparser 依賴。"""
    txt = open(path, encoding='utf-8').read()
    # ⚠ 先剝除註解列。BibTeX 允許 % 註解寫在 entry 內部，但下面的欄位
    #   正則是以「下一個 欄位名 =」為界，註解夾在中間會被吞進前一個欄位
    #   的值裡，整段中文註解就會印進參考文獻。2026-08-24 實際發生過一次
    #   （Friedman 那筆）。只剝整列註解，不動欄位值裡的 \% 。
    txt = re.sub(r'(?m)^[ \t]*%.*$', '', txt)
    out = {}
    for m in re.finditer(r'@(\w+)\s*\{\s*([^,]+),(.*?)\n\}', txt, re.S):
        kind, key, body = m.group(1).lower(), m.group(2).strip(), m.group(3)
        f = {}
        for fm in re.finditer(r'(\w+)\s*=\s*\{(.*?)\}\s*,?\s*(?=\n\s*\w+\s*=|\s*$)',
                              body, re.S):
            f[fm.group(1).lower()] = re.sub(r'\s+', ' ',
                                            fm.group(2)).strip()
        f['__type__'] = kind
        out[key] = f
    return out


def initials(given):
    """Arthur E. → A. E.；Hans-Christian → H.-C.；已是縮寫的原樣保留。"""
    parts = []
    for tok in given.split():
        if '-' in tok:
            parts.append('-'.join(p[0] + '.' for p in tok.split('-') if p))
        elif tok.endswith('.'):
            parts.append(tok)
        else:
            parts.append(tok[0] + '.')
    return ' '.join(parts)


def acm_authors(field):
    """ACM：Surname, F. M.，兩位以 and 連，三位以上末位前加 and。"""
    names = []
    for raw in re.split(r'\s+and\s+', field):
        raw = delatex(raw)
        if ',' in raw:
            sur, given = [x.strip() for x in raw.split(',', 1)]
            names.append('%s, %s' % (sur, initials(given)))
        else:
            toks = raw.split()
            names.append('%s, %s' % (toks[-1], initials(' '.join(toks[:-1])))
                         if len(toks) > 1 else raw)
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return '%s and %s' % tuple(names)
    return '%s, and %s' % (', '.join(names[:-1]), names[-1])


def fmt(entry):
    """回傳 [(文字, 是否斜體), ...]。刊名／會議名斜體，其餘正體。"""
    seg = []
    e = entry

    def add(t, it=False):
        if t:
            seg.append((t, it))

    # 作者串多半以縮寫的句點結尾（… , D.），再加一個句點會變 "D.."。
    au = acm_authors(e['author'])
    add('%s %s. %s. ' % (au if au.endswith('.') else au + '.', e['year'],
                         delatex(e['title']).rstrip('.')))

    if e['__type__'] == 'inproceedings':
        add('In ')
        add(delatex(e['booktitle']), True)
        tail = ''
        if e.get('series'):
            tail += ', ' + delatex(e['series'])
        if e.get('volume'):
            tail += ' ' + e['volume']
        if e.get('pages'):
            tail += ', ' + e['pages'].replace('--', '-')
        add(tail + '.')
        if e.get('note'):
            add(' ' + delatex(e['note']) + '.')
    else:
        add(delatex(e['journal']), True)
        tail = ' ' + e.get('volume', '')
        if e.get('number'):
            tail += ', ' + e['number']
        if e.get('pages'):
            tail += ', ' + e['pages'].replace('--', '-')
        add(tail.rstrip() + '.')

    if e.get('doi'):
        # ⚠ 網址要自成一個片段，排版端才認得出來、排成超連結。
        add(' DOI: ')
        add('https://doi.org/' + e['doi'])
    return seg


def acm_entries(keys):
    """依給定的鍵序回傳 ACM 格式片段；缺漏的鍵一併回報。"""
    bib = parse_bib()
    out, missing = [], []
    for k in keys:
        if k in bib:
            out.append((k, fmt(bib[k])))
        else:
            missing.append(k)
            out.append((k, [('[缺 refs.bib 條目：%s]' % k, False)]))
    return out, missing


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    b = parse_bib()
    print('refs.bib 共 %d 筆\n' % len(b))
    for i, (k, v) in enumerate(sorted(b.items()), 1):
        print('[%d] %s' % (i, ''.join(t for t, _ in fmt(v))))
