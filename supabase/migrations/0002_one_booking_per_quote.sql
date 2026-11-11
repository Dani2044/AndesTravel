-- One booking per quote. The API derives the idempotency key from the quote
-- (res-<quote_id>); this index also covers keys written before that change.
create unique index if not exists reservations_quote_uidx on reservations (quote_id);
