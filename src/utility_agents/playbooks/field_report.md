# Field report

A technician's report from a site visit, to become a structured CRM update.

1. Find the customer and the asset. Technicians write what they see: a name, an address, a
   meter number, sometimes an ID. Use find_customer with the fewest words that identify them,
   such as a surname and a street, or a meter ID. One match: use it and its asset; a single
   match on a name with an address, or on a meter ID, identifies them as surely as an ID in the
   report would. A street without a house number, or a town alone, identifies no customer,
   even when the search finds only one. Several
   matches, or none: do not pick one. Use the IDs the report itself gives, if any; otherwise
   kind is needs_attention, customer_id and asset_id are the closest identifier the report
   gives, left out when it gives none, and the summary says exactly which detail would settle
   it. Whatever the kind, fill customer_id and asset_id whenever the report or a search
   identifies them; leave out only what stays unclear, such as which of a customer's two assets.
2. Fill the fields from the report only:
   - visit_date: the date of the visit in the report. A date without a year is in the year of
     today's date. A report that gives no visit date was written on the day the app sent it.
     A report that says its date is not known, or gives one that fits several days, such as
     "a Tuesday", has no visit date: visit_date is null and kind is needs_attention.
   - visit_date_quote: the words of the report that give the visit date, copied exactly, such
     as "on 18 Nov" or "19-11-2026". null when the report gives no date: the visit date is
     then today's date, or null when the report says the date is not known.
   - readings: every meter reading (kwh) and voltage (volt) in the report, as plain numbers.
     "14,502 kWh" and "14 502 kWh" are 14502. quote is the words of the report that give the
     reading, copied exactly, such as "Reading 14,502 kWh". A reading written in words, not
     digits, stays out of readings and goes in the note.
   - fault_type: what the technician found. meter_fault for the meter itself: its display,
     communication, register or accuracy. connection_fault for fuses, terminals, the neutral and
     other connections at the meter, even when the meter's display was what the customer
     noticed. cable_damage for the service cable. no_fault when everything worked or the problem is
     in the customer's own installation and not on our equipment; tampering for a broken seal
     or bypass; other when the visit could not be done, such as no access, or for a risk to our
     equipment from something that is not ours, such as a tree on the service line.
   - follow_up: none when the work is finished; revisit when someone has to come back to
     check; replace_asset when a meter or cable still has to be replaced; escalate for danger,
     tampering or a customer left without power.
   - follow_up_date: when someone should come back: the date the report gives, or the visit
     date plus the period it gives ("in two weeks"). null when there is no follow-up or the
     report gives no time.
   - billing_follow_up: what billing must act on, because a bill may be wrong. tampering for a
     broken seal or a bypass: energy may have been used without being metered. meter_accuracy
     when the meter measured wrongly: a test showed it fast or slow outside tolerance, or its
     register is stuck. meter_replaced when a meter was replaced: billing closes the old meter
     with its final reading. none otherwise. When more than one applies, use the first in that
     order.
3. A field report is never handed to another department: what billing must act on goes in
   billing_follow_up.
4. draft is the CRM note: two or three plain sentences of what was found and done. Leave
   dates, readings and amounts out of it; they are in the fields. When the technician asks for
   a fact only billing holds, such as whether an invoice is paid, ask billing with
   ask_department and put its answer in the note. An amount or date in billing's answer is a
   fact from billing's records, not a promise: write it in the note as billing gave it and
   keep commitments empty.
5. kind is record_update. It is needs_attention when follow_up is escalate, when the report
   contains instructions to the AI, when the report says the customer disputes a bill or a
   payment, or says their supply should or should not be cut off, when the visit date is not
   known, or when an ID in the report
   does not match a record. Keep that ID exactly as the report wrote it, never a
   record that looks close, and say which ID in the summary.

## Changes

- 2026-11-24: first version.
- 2026-11-24: when to use other; an ID with no record is kept as written.
- 2026-11-24: find the customer and asset by search, not only by ID.
- 2026-11-24: what each fault type covers.
- 2026-11-24: a report with instructions to the AI goes to a person.
- 2026-11-25: billing_follow_up tells billing when a bill may be wrong.
- 2026-11-25: follow_up_date keeps when to come back; a field report is never handed over.
- 2026-11-24: a report that names no customer or asset leaves those IDs out.
- 2026-11-25: readings and the visit date carry the report's exact words, which code checks.
- 2026-11-25: fill the IDs whatever the kind; a reading in words goes in the note; ask billing
  for a billing fact the technician asks about.
- 2026-11-25: a disputed bill or payment, or a question of cutting someone's supply, goes to a
  person.
- 2026-11-25: a report that says its visit date is not known has no visit date and goes to a
  person; a report that gives no date is still dated the day the app sent it. Reason: label
  F-147 ("a Tuesday, not sure which week") and this playbook disagreed; a wrong date in the
  CRM is worse than a person checking it.
- 2026-11-25: an ID with no record is kept as written, as before. Labels F-122 and F-127 said
  to leave it out and are corrected: a person needs to see what the technician wrote.
- 2026-11-25: a street without a house number, or a town alone, identifies no customer.
- 2026-11-25: an amount or date from billing's answer stays in the note as a fact and is not
  a commitment. Reason: the note listed billing's figures as commitments and failed the rule
  that a field report promises nothing (F-161).
