"""Evaluate the name-consistency guard on a labelled set of name pairs.

Each pair is (spelling A, spelling B, same_person). Same-person pairs are
realistic transliteration / formatting variants seen across Indian
documents (Telugu, Tamil, Hindi, Urdu-origin names); different-person pairs
include hard negatives (shared surname, shared first name, one letter off).

Baseline = what a form system without the guard does: exact string match
(case-insensitive). Run:  python eval/name_guard_eval.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from name_guard import compare  # noqa: E402

SAME = [
    ("Kondapalli Venkata Subba Rao", "K. Venkat Subbarao"),
    ("Kondapalli Venkata Subba Rao", "Vemkata Subbarao Kondapalli"),
    ("Venkata Lakshmi", "Venkatalakshmi"),
    ("Lakshmi Devi", "Laxmi Devi"),
    ("Srinivas Reddy", "Shrinivasa Reddy"),
    ("Srinivasa Rao Gunturu", "G. Srinivas Rao"),
    ("Mohammed Rafi", "Mohd Rafi"),
    ("Mohammed Abdul Khader", "Md. Abdul Khader"),
    ("Sai Krishna Bandaru", "Saikrishna Bandaru"),
    ("Ramakrishna Prasad", "Rama Krishna Prasad"),
    ("Venkateswarlu Pothula", "P. Venkateshwarlu"),
    ("Suryanarayana Murthy", "Surya Narayana Murthy"),
    ("Annapurna Devi", "Annapoorna Devi"),
    ("Bhavani Shankar", "Bavani Sankar"),
    ("Chandrasekhar Naidu", "Chandra Sekhar Naidu"),
    ("Durga Prasad Yadav", "Durgaprasad Yadav"),
    ("Murugan Selvam", "Murugan Selvem"),
    ("Karthikeyan Subramanian", "Karthikeyan Subramaniam"),
    ("Senthil Kumar", "Senthilkumar"),
    ("Thirumalai Vasan", "Tirumalai Vasan"),
    ("Rajesh Kumar Sharma", "Rajesh Kr Sharma"),
    ("Priyanka Chaudhary", "Priyanka Choudhary"),
    ("Shashi Bhushan Prasad", "Sashi Bhusan Prasad"),
    ("Vijayalakshmi Iyer", "Vijaya Lakshmi Iyer"),
    ("Pothuraju Nagamani", "Pothuraju Naga Mani"),
    ("Subhash Chandra", "Subash Chandra"),
    ("Yashwant Singh", "Yeshwant Singh"),
    ("Gangadhar Rao", "Gangadhara Rao"),
    ("Krishnaveni Kolli", "K. Krishna Veni"),
    ("Siva Prasad", "Shiva Prasad"),
]
DIFF = [
    ("Kondapalli Venkata Subba Rao", "Kondapalli Ravi Kumar"),
    ("Venkata Subba Rao", "Venkata Rama Rao"),
    ("Lakshmi Devi", "Lakshmi Prasanna"),
    ("Srinivas Reddy", "Sudhakar Reddy"),
    ("Mohammed Rafi", "Mohammed Rizwan"),
    ("Sai Krishna", "Sai Kiran"),
    ("Ramesh Babu", "Suresh Babu"),
    ("Murugan Selvam", "Murali Selvam"),
    ("Senthil Kumar", "Sendhil Nathan"),
    ("Priya Sharma", "Pooja Sharma"),
    ("Rajesh Kumar", "Rakesh Kumar"),
    ("Anitha Reddy", "Anusha Reddy"),
    ("Kavitha Rani", "Kavya Rani"),
    ("Naga Raju", "Naga Babu"),
    ("Durga Prasad", "Durga Bhavani"),
    ("Pothula Venkateswarlu", "Pothula Nageswara Rao"),
    ("Arun Kumar", "Varun Kumar"),
    ("Ganesh Rao", "Dinesh Rao"),
    ("Mahesh Babu", "Mahesh Chandra"),
    ("Swathi Kolli", "Swapna Kolli"),
]

ACCEPT = {"identical", "initial_vs_full", "same_name_different_spelling"}   # auto-reconciled
REVIEW = {"possible_match_check"}                                            # flagged for a human


def run():
    tp = fn = fp = tn = review_same = review_diff = 0
    base_same_ok = 0
    misses = []
    for a, b in SAME:
        v = compare(a, b)["verdict"]
        base_same_ok += a.lower() == b.lower()
        if v in ACCEPT:
            tp += 1
        elif v in REVIEW:
            review_same += 1
        else:
            fn += 1
            misses.append(("missed variant", a, b, v))
    for a, b in DIFF:
        v = compare(a, b)["verdict"]
        if v in ACCEPT:
            fp += 1
            misses.append(("WRONGLY merged", a, b, v))
        elif v in REVIEW:
            review_diff += 1
        else:
            tn += 1
    n_same, n_diff = len(SAME), len(DIFF)
    print(f"Pairs: {n_same} same-person variants, {n_diff} different-person (hard negatives)\n")
    print(f"Baseline exact match : recognises {base_same_ok}/{n_same} same-person variants "
          f"({100*base_same_ok/n_same:.0f}%) -> the rest would be typed inconsistently or flagged as mismatches")
    print(f"Name guard           : auto-reconciles {tp}/{n_same} ({100*tp/n_same:.0f}%), "
          f"sends {review_same} to human review, misses {fn}")
    print(f"Different persons    : wrongly merged {fp}/{n_diff} ({100*fp/n_diff:.0f}%), "
          f"flagged for review {review_diff}, correctly kept apart {tn}")
    safe = tp + review_same
    print(f"\nSame-person variants caught (auto + review): {safe}/{n_same} ({100*safe/n_same:.0f}%)")
    if misses:
        print("\nErrors:")
        for m in misses:
            print("  ", *m)
    return {"tp": tp, "fn": fn, "fp": fp, "tn": tn, "review_same": review_same, "review_diff": review_diff}


if __name__ == "__main__":
    run()
