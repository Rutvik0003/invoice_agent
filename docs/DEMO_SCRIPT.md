# Demo script

Two versions: **(A)** the 5-minute video you record in real mode with your Gmail, **(B)** the live interview, mostly in
the demo so the interviewers can follow along on their own laptops. One or two sentences to say at each step.

## Before you start (10 minutes before)

1. Open the live URL so the free instance wakes up (it sleeps when idle; the first load can take a minute).
2. Run the smoke test: `python backend/scripts/smoke_test.py https://invoice-agent-9ukc.onrender.com --no-ai`
   → every check PASS (health, OCR, real mode locked, demo inbox, reset).
3. Real mode → sign in with Google once (the sign-in of a Google app in *Testing* expires after 7 days).
4. Settings → **Reset demo data** in real mode if you want a clean ledger (your Gmail stays connected).
5. For the video: email yourself 3–4 golden invoices from another address, with realistic subjects:
   `01_happy_clean.pdf` (Paid), `03_A_split_overrun.pdf` (overrun), `05_C_no_po.pdf` (no PO),
   `07_E_wrong_gst.pdf` (wrong GST). Attach one per email.

---

## A. The 5-minute video (real mode, your Gmail)

| Time | Click | Say |
|---|---|---|
| 0:00 | Start screen | "An AP agent for GST invoices: it reads a bill from email and says Paid, Needs human verification or Rejected, with the reasons. AI reads, OCR verifies, code decides." |
| 0:20 | **Real mode → Sign in with Google** → account → allow read-only Gmail | "Read-only Gmail. Only my account gets into real mode; anyone else is offered the demo." |
| 0:45 | **Inbox** (bills filter on) → open the Vertex email → **Check this bill** | "It lists only emails with invoice attachments. I pick which bills to check." |
| 1:00 | Live run: stages light up; point at the **green boxes** on the invoice | "One AI call reads the fields. Then, without AI, every key value is found on the page: these boxes are where the total, GSTIN and invoice number really are." |
| 1:40 | Decision card **Paid** → ledger summary | "All 8 stages passed, so it's paid and the PO ledger moved. Any number links back to the page or the PO line." |
| 2:00 | Back to Inbox → tick **overrun + no-PO + wrong GST** → **Check 3 bills (batch)** → **Running** | "Several bills run as a batch, one after the other within the free-tier limits. I can leave; Running shows what is still going." |
| 2:40 | Batch result: Rejected (wrong GST) → **Reply to vendor** → Inbox thread | "A reject drafts the vendor reply, in the same email thread, saying what is wrong and what to change." |
| 3:20 | **Verification queue** → overrun: read the reason → **Compare with PO** | "When the rules are not sure, a person decides. One check per invoice; here the bill exceeds what is left on the PO." |
| 3:50 | No-PO invoice: the suggested PO is pre-selected → note → **Verify & pay** | "No PO was printed; the agent found the matching PO. The person confirms it and pays in one step, logged with a note." |
| 4:20 | **Dashboard** | "Every run, its decision and why; the most common reasons; time saved." |
| 4:40 | **Test Suite** → reports tab | "283 of 283 decisions right on generated invoices, 42 of 42 on unseen layouts; verification catches 100% of wrong AI values." |
| 5:00 | end | |

## B. The live interview (demo; ask them to open the link too)

1. **Start → Try demo.** "Each of you gets a private sandbox; nothing you do reaches anyone else."
2. **Inbox → Vertex (01) → Check this bill.** Paid. Point at the green boxes and the "Expected: Paid ✓" badge.
3. **Kosmic Cartons (03).** Needs verification: PO overrun. "Earlier bills took 88% of the PO; this one would exceed it."
4. **Kapadia "payment reminder" (04).** Rejected: duplicate. "Already paid in August; the number is written INV/1304 instead of INV-01304, and the normalised number still matches."
5. **Shubham Advertising (05).** No PO → the agent infers PO-2026-1201 → **Verification queue** → *Verify & pay*.
6. **Ramesh Packaging "new bank account" (06).** Fraud flag: "bank details changed; verify through a known contact, never the contact on the invoice."
7. **Ramesh scanned copy (08).** The blurry scan: OCR boxes; the invoice number could not be confirmed → a person checks it. "It never guesses."
8. **Run 01 again.** Rejected: "already approved and paid". "Duplicates are caught by file and by number."
9. **Model switch:** on any failed or new run, pick another Gemini model (each has its own free-tier limit).
10. **Test Suite & Evaluation** page: the reports and the confusion matrix.
11. Questions. If they ask "what would you do next": goods-receipt 3-way match, ERP connectors, learning from the
    corrections people make in the Verification queue.

## If something goes wrong

| Problem | What to do |
|---|---|
| "The AI model has reached its rate limit" / "busy right now" | Click **Try · gemini-3.6-flash** (or another model) on the same card; each model has its own limit. Real mode can also use Groq. |
| First page load is slow | The free instance is waking up; wait a minute (that's why step 1 above). |
| Google sign-in error | Use the demo for the interview; for the video, sign in again (7-day expiry in Testing mode). |
| A re-run says "already paid" | That is correct behaviour; Settings → Reset demo data to start over. |
| Something unexpected in a live run | Open the **Audit trail** tab: every stage and check is listed with its evidence. |
