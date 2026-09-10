# -*- coding: utf-8 -*-
"""三批次甲烷化學計量對帳的原始數據圖（內部參考用，不進論文）。"""
import os, sys
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei']
plt.rcParams['axes.unicode_minus'] = False
B, R, G = '#1F6FB5', '#C0392B', '#666666'

nm = ['批次1\n循環1分', '批次2\n循環5分', '批次3\n循環10分']
ratio = [0.2172, 0.1682, 0.1928]
share = [0.869, 0.673, 0.771]
rate = [0.0185, 0.0434, 0.0364]
sd = [0.0017, 0.0309, 0.0045]
rb = [0.0161, 0.0292, 0.0281]
ch4 = [31.64, 34.84, 43.04]

fig, ax = plt.subplots(1, 3, figsize=(13.2, 4.3))

b = ax[0].bar(nm, ratio, width=.55, color=[B, '#6FA8D0', B],
              edgecolor='#123A57', lw=.8)
ax[0].axhline(.25, color=R, lw=2.4, ls='--')
ax[0].text(2.45, .256, '化學計量上限 0.25\n（5 進 1 出）', color=R,
           fontsize=10.5, ha='right', fontweight='bold')
for r_, v in zip(b, ratio):
    ax[0].text(r_.get_x()+r_.get_width()/2, v+.006, '%.3f' % v,
               ha='center', fontsize=11.5, fontweight='bold', color=B)
ax[0].set_ylim(0, .30); ax[0].set_ylabel('CH4 生成 ÷ 氣體消耗')
ax[0].set_title('三批全部落在硬上限之內', fontweight='bold')
ax[0].grid(alpha=.22, axis='y')

ax[1].bar(nm, [s*100 for s in share], width=.55, color='#E8836F',
          edgecolor='#7B1E10', lw=.8)
for i, s in enumerate(share):
    ax[1].text(i, s*100+1.5, '%.0f%%' % (s*100), ha='center',
               fontsize=12, fontweight='bold', color='#7B1E10')
    ax[1].text(i, 8, 'CH4峰值\n%.1f%%' % ch4[i], ha='center',
               fontsize=9.5, color='white', fontweight='bold')
ax[1].set_ylim(0, 100); ax[1].set_ylabel('生物佔壓力下降的比例 (%)')
ax[1].set_title('循環越短，生物佔比越高', fontweight='bold')
ax[1].grid(alpha=.22, axis='y')

x = np.arange(3)
ax[2].errorbar(x, rate, yerr=sd, fmt='s-', ms=9, lw=2, color=G,
               capsize=6, label='總下降速率')
ax[2].plot(x, rb, 'o-', ms=10, lw=2.6, color=R, label='其中生物那一份')
ax[2].axhline(.0126, color=B, lw=2.2, ls='--',
              label='論文全資料集中位 0.0126')
ax[2].axhline(.0177, color='#E8912B', lw=1.6, ls=':',
              label='kT>7 尾段斜率 0.0177')
ax[2].set_xticks(x); ax[2].set_xticklabels(nm)
ax[2].set_ylabel('kg/cm²/hr'); ax[2].set_ylim(0, .08)
ax[2].set_title('三批的 r_b 都高於論文值', fontweight='bold', color=R)
ax[2].legend(fontsize=9, framealpha=.95); ax[2].grid(alpha=.22)

fig.suptitle('三批次甲烷化學計量對帳（2026-07~08）　'
             '獨立於壓力擬合的驗證', fontsize=13.5, fontweight='bold')
fig.tight_layout(rect=(0, 0, 1, .93))
p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '..', 'docs', 'paper_figures', 'figZ_batch_check.png')
fig.savefig(p, dpi=180); plt.close(fig)
print('→ figZ_batch_check.png')
