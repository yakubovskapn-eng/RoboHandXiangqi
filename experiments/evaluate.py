"""
Експеримент для звіту: точність визначення ходу на випадкових партіях і стійкість до шуму.
"""
import json
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xiangqi_robot import (  # noqa: E402
    Board,
    Move,
    MoveDetectionError,
    detect_move,
    detect_move_from_pieces,
    detect_squares,
    pseudo_legal_moves,
)

N_GAMES = 30
MAX_PLIES = 120
NOISE_LEVELS = (1, 2, 3)
NOISE_TRIALS = 5
SEED = 2026


def play_game(seed):
    """
    Випадкова партія ходів.
    Повертає список: дошка, хід, після
    """
    rng = random.Random(seed)
    board = Board.start()
    samples = []
    for _ in range(MAX_PLIES):
        moves = list(pseudo_legal_moves(board))
        if not moves:
            break
        frm, to = rng.choice(moves)
        real = Move(board.piece_at(frm), frm, to, captured=board.piece_at(to))
        after = board.apply(real)
        samples.append((board, real, after))
        if real.captured in ("k", "K"):
            break
        board = after
    return samples


def occupancy(colors):
    return [[1 if v else 0 for v in row] for row in colors]


def noisy(colors, k, rng):
    out = [row[:] for row in colors]
    cells = rng.sample([(r, c) for r in range(10) for c in range(9)], k)
    for r, c in cells:
        out[r][c] = rng.choice([v for v in (0, 1, 2) if v != out[r][c]])
    return out


def classify(board, noisy_colors, real, check_rules):
    try:
        found = detect_move(board, noisy_colors, check_rules=check_rules)
    except MoveDetectionError:
        return "rejected"
    return "correct" if found == real else "wrong"


def pct(x, n):
    return round(100.0 * x / n, 2) if n else 0.0


def main():
    samples = []
    for g in range(N_GAMES):
        samples.extend(play_game(SEED + g))
    n = len(samples)
    captures = sum(1 for _, real, _ in samples if real.is_capture)

    ok_colors = ok_pieces = 0
    times_us = []
    for board, real, after in samples:
        colors = after.colors()
        t0 = time.perf_counter_ns()
        found = detect_move(board, colors)
        times_us.append((time.perf_counter_ns() - t0) / 1000.0)
        ok_colors += found == real
        ok_pieces += detect_move_from_pieces(board, after) == real


    occ_ok = occ_fail_capture = occ_fail_other = 0
    for board, real, after in samples:
        try:
            frm, to, _ = detect_squares(occupancy(board.colors()), occupancy(after.colors()))
            occ_ok += (frm, to) == (real.from_sq, real.to_sq)
        except MoveDetectionError:
            if real.is_capture:
                occ_fail_capture += 1
            else:
                occ_fail_other += 1

    rng = random.Random(SEED)
    noise = {}
    for k in NOISE_LEVELS:
        for check_rules in (True, False):
            counts = {"correct": 0, "rejected": 0, "wrong": 0}
            for board, real, after in samples:
                for _ in range(NOISE_TRIALS):
                    counts[classify(board, noisy(after.colors(), k, rng), real, check_rules)] += 1
            total = sum(counts.values())
            noise[f"k={k},rules={'on' if check_rules else 'off'}"] = {
                "trials": total,
                **{key: counts[key] for key in counts},
                **{key + "_pct": pct(counts[key], total) for key in counts},
            }

    srt = sorted(times_us)
    results = {
        "setup": {
            "games": N_GAMES, "max_plies": MAX_PLIES, "seed": SEED,
            "noise_levels": list(NOISE_LEVELS), "noise_trials_per_ply": NOISE_TRIALS,
        },
        "plies": n,
        "captures": captures,
        "captures_pct": pct(captures, n),
        "colors_correct": ok_colors,
        "colors_correct_pct": pct(ok_colors, n),
        "pieces_correct": ok_pieces,
        "pieces_correct_pct": pct(ok_pieces, n),
        "occupancy_only": {
            "correct": occ_ok, "correct_pct": pct(occ_ok, n),
            "error_on_capture": occ_fail_capture, "error_other": occ_fail_other,
        },
        "noise": noise,
        "time_us": {
            "mean": round(statistics.mean(times_us), 1),
            "median": round(statistics.median(times_us), 1),
            "p95": round(srt[int(0.95 * (len(srt) - 1))], 1),
            "max": round(srt[-1], 1),
        },
    }

    out = Path(__file__).with_name("results.json")
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nЗбережено: {out}")


if __name__ == "__main__":
    main()
