Read exact current server-bound state at read_state_path from the current packet.
Use a read_state_path supplied in your current packet, not another role's example.
Empty path reads the full role/task state when needed. Lists page by limit; text by
characters. Follow next_offset with
the same path and prior state_digest as expected_state_digest; changed state rejects
continuation to prevent mixing versions. You cannot select another actor/task.
This is bookkeeping, not evidence observation or a completed check.