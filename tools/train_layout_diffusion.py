#!/usr/bin/env python3
"""Train a tiny diffusion model on 64x64 layout crops from the reference map.

Purpose is to measure the time cost of training a *layout* model, not to produce a final artefact.
The layout only needs 64-128 resolution (structures above ~96 blocks), so the model is small and the
data is small: the reference map downsampled 4x yields crops that fit in a megabyte.

Usage:
  python train_layout_diffusion.py --minutes 8            # train for a wall-clock budget
  python train_layout_diffusion.py --steps 200 --smoke     # just measure step time
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).parent))
from patch_synth import load_tiles  # noqa: E402


# ---------------------------------------------------------------- data
def build_crops(world: Path, crop=64, stride=16, downsample=4):
    tiles = load_tiles(world, [f"r.{i}.{j}" for i in range(4) for j in range(4)])
    crops = []
    for reg, (g, valid) in tiles.items():
        small = g[::downsample, ::downsample]
        ok = valid[::downsample, ::downsample]
        h, w = small.shape
        for z in range(0, h - crop + 1, stride):
            for x in range(0, w - crop + 1, stride):
                if ok[z:z + crop, x:x + crop].mean() > 0.99:
                    crops.append(small[z:z + crop, x:x + crop].astype(np.float32))
    a = np.stack(crops)
    lo, hi = np.percentile(a, 1), np.percentile(a, 99)
    a = (a - lo) / max(hi - lo, 1e-6) * 2.0 - 1.0          # to [-1, 1]
    return np.clip(a, -1.2, 1.2), float(lo), float(hi)


# ---------------------------------------------------------------- model
class TimeEmbed(nn.Module):
    def __init__(self, dim):
        super().__init__()
        self.dim = dim

    def forward(self, t):
        half = self.dim // 2
        freqs = torch.exp(-math.log(10000) * torch.arange(half, device=t.device) / half)
        return torch.cat([torch.sin(t[:, None] * freqs), torch.cos(t[:, None] * freqs)], dim=1)


class Block(nn.Module):
    def __init__(self, cin, cout, temb):
        super().__init__()
        self.conv1 = nn.Conv2d(cin, cout, 3, padding=1)
        self.conv2 = nn.Conv2d(cout, cout, 3, padding=1)
        self.norm1 = nn.GroupNorm(8, cin)
        self.norm2 = nn.GroupNorm(8, cout)
        self.temb = nn.Linear(temb, cout)
        self.skip = nn.Conv2d(cin, cout, 1) if cin != cout else nn.Identity()

    def forward(self, x, t):
        h = self.conv1(F.silu(self.norm1(x)))
        h = h + self.temb(t)[:, :, None, None]
        h = self.conv2(F.silu(self.norm2(h)))
        return h + self.skip(x)


class TinyUNet(nn.Module):
    def __init__(self, base=32, temb=64):
        super().__init__()
        self.temb = nn.Sequential(TimeEmbed(temb), nn.Linear(temb, temb), nn.SiLU(),
                                  nn.Linear(temb, temb))
        self.in_conv = nn.Conv2d(1, base, 3, padding=1)
        self.d1 = Block(base, base, temb)
        self.d2 = Block(base, base * 2, temb)
        self.mid = Block(base * 2, base * 2, temb)
        self.u1 = Block(base * 2 + base, base, temb)
        self.u2 = Block(base + base, base, temb)
        self.out = nn.Conv2d(base, 1, 3, padding=1)

    def forward(self, x, t):
        te = self.temb(t)
        h0 = self.in_conv(x)
        h1 = self.d1(h0, te)
        h2 = self.d2(F.avg_pool2d(h1, 2), te)
        m = self.mid(h2, te)
        u1 = F.interpolate(m, scale_factor=2, mode="nearest")
        u1 = self.u1(torch.cat([u1, h1], dim=1), te)
        u2 = self.u2(torch.cat([u1, h0], dim=1), te)
        return self.out(u2)


def beta_schedule(steps=200):
    return torch.linspace(1e-4, 0.02, steps)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default="G:/HMCL/.minecraft/versions/1.20.1-Liminalism/saves/静谧山谷-拉斐丽")
    ap.add_argument("--crop", type=int, default=64)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--steps", type=int, default=0, help="0 = run for --minutes")
    ap.add_argument("--minutes", type=float, default=8.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--smoke", action="store_true", help="measure step time only")
    ap.add_argument("--out", default="preview/fits/layout_ddpm.pt")
    args = ap.parse_args()

    torch.set_num_threads(32)
    t0 = time.time()
    data, lo, hi = build_crops(Path(args.world), args.crop)
    print(f"crops: {data.shape}  (heights {lo:.0f}..{hi:.0f})  built in {time.time()-t0:.1f}s")
    X = torch.from_numpy(data).unsqueeze(1)

    model = TinyUNet()
    nparam = sum(p.numel() for p in model.parameters())
    print(f"model: {nparam/1e6:.2f}M parameters")

    betas = beta_schedule(200)
    abar = torch.cumprod(1 - betas, dim=0)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)

    n = len(X)
    step = 0
    t_start = time.time()
    t_last = t_start
    losses = []
    while True:
        idx = torch.randint(0, n, (min(args.batch, n),))
        x0 = X[idx]
        t = torch.randint(0, len(betas), (len(idx),))
        noise = torch.randn_like(x0)
        a = abar[t][:, None, None, None]
        xt = a.sqrt() * x0 + (1 - a).sqrt() * noise
        pred = model(xt, t.float())
        loss = F.mse_loss(pred, noise)
        opt.zero_grad()
        loss.backward()
        opt.step()

        step += 1
        losses.append(float(loss))
        if step % 20 == 0:
            now = time.time()
            rate = 20 / (now - t_last)
            t_last = now
            print(f"  step {step:5d}  loss {np.mean(losses[-20:]):.4f}  "
                  f"{rate:.1f} steps/s  elapsed {now-t_start:.0f}s")
        if args.smoke and step >= 100:
            break
        if args.steps and step >= args.steps:
            break
        if (time.time() - t_start) / 60.0 >= args.minutes:
            break

    dt = time.time() - t_start
    print(f"\ntrained {step} steps in {dt:.0f}s  ({step/dt:.1f} steps/s)  final loss {np.mean(losses[-50:]):.4f}")
    if not args.smoke:
        torch.save({"model": model.state_dict(), "lo": lo, "hi": hi}, args.out)
        print(f"-> {args.out}")

        # sample
        model.eval()
        with torch.no_grad():
            x = torch.randn(4, 1, args.crop, args.crop)
            for i in reversed(range(len(betas))):
                tt = torch.full((4,), float(i))
                eps = model(x, tt)
                a, b = abar[i], betas[i]
                x = (x - b / (1 - a).sqrt() * eps) / (1 - b).sqrt()
                if i > 0:
                    x = x + b.sqrt() * torch.randn_like(x)
        s = x[:, 0].numpy()
        from PIL import Image
        grid = np.concatenate([np.concatenate([s[0], s[1]], axis=1),
                               np.concatenate([s[2], s[3]], axis=1)], axis=0)
        g = ((grid + 1) / 2 * 255).clip(0, 255).astype(np.uint8)
        Image.fromarray(g).resize((512, 512), Image.NEAREST).save("preview/images/layout_samples.png")
        print("-> preview/images/layout_samples.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
