"""notification-triage — mute ad/marketing noise, keep what matters.

Inspired by "Quiet marketing notifications on Android": for each incoming
notification, JuL answers one yes/no `Noul` — "is this advertising/marketing?".
Nothing is deleted; noisy ones are just silenced. The Noul answer is a
probability, so we can set a threshold instead of a hard yes/no.

Run:
    python notification-triage/run.py
    python notification-triage/run.py --threshold 0.6
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.jul_helper import get_client, Noul, NoulCriteria  # noqa: E402

NOTIFICATIONS = [
    "Your OTP code is 481920. Do not share it with anyone.",
    "🔥 FLASH SALE! 50% off everything for the next 3 hours only — shop now!",
    "Mom: are you coming for dinner on Sunday?",
    "You've earned 500 bonus points! Upgrade to Premium to unlock rewards.",
    "Reminder: your flight AF1234 departs tomorrow at 08:15 from gate D22.",
    "We miss you! Here's 20% off your next order 💜 come back and save.",
    "Payment of $1,204.00 to Landlord LLC was successful.",
    "Congratulations! You may have won a free iPhone. Tap to claim now!!!",
    "Dr. Klein's office: your appointment is confirmed for Thursday 14:00.",
    "Last chance ⏰ your cart is waiting — complete checkout and get free shipping.",
]


def triage(client, notifications, threshold):
    """One Noul per notification. The notification is the state being judged."""
    question = {
        "is_ad": Noul(
            instructions="Is this notification advertising, marketing, or promotional "
                         "noise, as opposed to something personal, transactional, or "
                         "time-sensitive?",
            criteria=NoulCriteria(
                true="an ad, promotion, sale, upsell, or re-engagement nudge",
                false="personal, transactional, security, or otherwise important",
            ),
        )
    }
    results = []
    for text in notifications:
        resp = client.system_one(state=text, questions=question)
        p_ad = resp.nouls["is_ad"].noul
        results.append((text, p_ad, p_ad >= threshold))
    return results


def run(threshold: float) -> None:
    client = get_client()
    print(f"Muting notifications with P(ad/marketing) >= {threshold}\n")
    kept, muted = [], []
    for text, p_ad, is_ad in triage(client, NOTIFICATIONS, threshold):
        (muted if is_ad else kept).append((text, p_ad))

    print(f"KEPT ({len(kept)}) — you'll be notified:")
    for text, p in kept:
        print(f"  [ad {p:4.2f}]  {text}")
    print(f"\nMUTED ({len(muted)}) — silenced, not deleted:")
    for text, p in muted:
        print(f"  [ad {p:4.2f}]  {text}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Silence ad/marketing notifications, powered by local JuL.")
    ap.add_argument("--threshold", type=float, default=0.5, help="mute when P(ad) >= threshold (0..1)")
    args = ap.parse_args()
    run(args.threshold)
