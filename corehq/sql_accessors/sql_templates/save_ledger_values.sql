DROP FUNCTION IF EXISTS save_ledger_values(TEXT, form_processor_ledgervalue, form_processor_ledgertransaction[]);

CREATE FUNCTION save_ledger_values(
    case_ids TEXT,
    ledger_value form_processor_ledgervalue,
    ledger_transactions form_processor_ledgertransaction[]
) RETURNS VOID AS $$
DECLARE
    ledger_transaction form_processor_ledgertransaction;
    array_index INT := 1;
BEGIN
    IF ledger_value.id IS NOT NULL THEN
        UPDATE form_processor_ledgervalue SET
            balance = ledger_value.balance,
            last_modified = ledger_value.last_modified
        WHERE
            id = ledger_value.id;
    ELSE
        INSERT INTO form_processor_ledgervalue (
            case_id, section_id, entry_id, balance, last_modified
        ) VALUES (
            ledger_value.case_id, ledger_value.section_id, ledger_value.entry_id,
            ledger_value.balance, ledger_value.last_modified
        );
    END IF;

    -- insert new transactions
    FOREACH ledger_transaction IN ARRAY ledger_transactions
    LOOP
        IF ledger_transaction.id IS NOT NULL THEN
            RAISE EXCEPTION 'Updating ledger transactions is not supported';
        ELSE
            INSERT INTO form_processor_ledgertransaction (
                form_id, server_date, report_date, type, case_id, entry_id, section_id,
                user_defined_type, delta, updated_balance
            ) VALUES (
                ledger_transaction.form_id, ledger_transaction.server_date, ledger_transaction.report_date, ledger_transaction.type,
                ledger_transaction.case_id, ledger_transaction.entry_id, ledger_transaction.section_id,
                ledger_transaction.user_defined_type, ledger_transaction.delta, ledger_transaction.updated_balance
            );
        END IF;
    END LOOP;
END
$$ LANGUAGE 'plpgsql';
