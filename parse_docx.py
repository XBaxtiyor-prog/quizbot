"""
savollar.docx formatini o'qib, SQLite bazasiga yozadi.

Kutilayotgan format (Word hujjatida):
---
1. Savol matni?
A) To'g'ri javob
B) Noto'g'ri variant 1
C) Noto'g'ri variant 2
D) Noto'g'ri variant 3
To'g'ri javob: A

yoki

1. Savol matni?
A) Variant 1
B) Variant 2
C) Variant 3
D) Variant 4
* A  (yulduzcha bilan belgilangan to'g'ri javob)
---
"""

import re
import sqlite3
import logging
from docx import Document

logger = logging.getLogger(__name__)


def clean_option(text: str) -> str:
    text = text.strip()
    text = re.sub(r'^[A-Da-d][).\s]+', '', text)
    return text.strip()


def parse_and_save(docx_path: str, db_path: str) -> int:
    doc = Document(docx_path)
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    questions = []
    i = 0
    while i < len(paragraphs):
        line = paragraphs[i]

        if re.match(r'^\d+[.)]\s+.+', line):
            question_text = re.sub(r'^\d+[.)]\s+', '', line).strip()
            options = {}
            correct_letter = None
            i += 1

            while i < len(paragraphs):
                cur = paragraphs[i]

                opt_match = re.match(r'^([A-Da-d])[).]\s*(.+)', cur)
                if opt_match:
                    letter = opt_match.group(1).upper()
                    value = opt_match.group(2).strip()
                    options[letter] = value
                    i += 1
                    continue

                correct_match = re.match(
                    r"^(?:To['']g['']ri\s+javob|Javob|Answer)[:\s]+([A-Da-d])",
                    cur, re.IGNORECASE
                )
                if correct_match:
                    correct_letter = correct_match.group(1).upper()
                    i += 1
                    continue

                star_match = re.match(r'^\*\s*([A-Da-d])', cur)
                if star_match:
                    correct_letter = star_match.group(1).upper()
                    i += 1
                    continue

                if re.match(r'^\d+[.)]\s+', cur):
                    break

                i += 1

            if len(options) >= 4 and correct_letter and correct_letter in options:
                correct_answer = options[correct_letter]
                wrong_options = [v for k, v in options.items() if k != correct_letter]
                while len(wrong_options) < 3:
                    wrong_options.append("—")
                questions.append({
                    "question": question_text,
                    "correct_answer": correct_answer,
                    "wrong1": wrong_options[0],
                    "wrong2": wrong_options[1],
                    "wrong3": wrong_options[2],
                })
            else:
                logger.warning(
                    f"Savol o'tkazib yuborildi: '{question_text[:50]}...' "
                    f"(variantlar: {list(options.keys())}, to'g'ri: {correct_letter})"
                )
        else:
            i += 1

    if not questions:
        raise ValueError(
            "Hech qanday savol topilmadi! "
            "Iltimos, savollar.docx formatini tekshiring:\n"
            "1. Savol?\nA) ...\nB) ...\nC) ...\nD) ...\nTo'g'ri javob: A"
        )

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("DELETE FROM questions")
    c.executemany("""
        INSERT INTO questions (question, correct_answer, wrong1, wrong2, wrong3)
        VALUES (:question, :correct_answer, :wrong1, :wrong2, :wrong3)
    """, questions)
    conn.commit()
    conn.close()

    logger.info(f"{len(questions)} ta savol bazaga yozildi.")
    return len(questions)


if __name__ == "__main__":
    import os
    import sys
    logging.basicConfig(level=logging.INFO)
    docx = sys.argv[1] if len(sys.argv) > 1 else "savollar.docx"
    db = sys.argv[2] if len(sys.argv) > 2 else "quiz_bot.db"
    if not os.path.exists(docx):
        print(f"❌ Fayl topilmadi: {docx}")
        sys.exit(1)
    n = parse_and_save(docx, db)
    print(f"✅ {n} ta savol yozildi.")
