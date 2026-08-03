-- BIC v1.0 — Slice 1C · `#status` is a composite command, not a tool
--
-- 20260803000004 registered `status` as a tool. That handler had to invoke
-- `leads_today` and `crm_list_clients` to do its job — and tools.invoke() calls
-- db.reset_query_count() on a single thread-local, so a tool that invokes tools
-- resets the OUTER invocation's counter and its audit row under-reports
-- db_queries. Silently wrong numbers in an audit table are worse than none.
--
-- Making invoke() nest-safe means editing bic/tools.py, which belongs to CLOSED
-- Slice 1B — that requires an ACP, not an opportunistic edit. So `#status` is
-- composed at the dispatch site (webhook.compose_status) from two ordinary
-- audited invocations instead.
--
-- This is arguably the better design regardless: each constituent tool is gated
-- by policy on its own terms, and joining their output is presentation, which
-- is the transport layer's job.
--
-- The row is DEACTIVATED rather than deleted so bic_tool_invocations keeps
-- referential meaning for any rows already written under this code, and so the
-- history of the decision survives in the registry itself.

update bic_tool_defs
   set active = false,
       description = 'RETIRED — #status is composed at the dispatch site from '
                     'leads_today + crm_list_clients. A tool that invokes tools '
                     'corrupts the outer audit row''s db_queries counter. '
                     'Re-activate only after invoke() is made nest-safe (ACP).'
 where code = 'status';
