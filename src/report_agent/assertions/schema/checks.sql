-- S2 review queries. The transaction supplies immutable, authorized facts as :ctx;
-- :row is the C1-validated envelope. :catalog is this revision's actions.json.
-- One returned row per failed rule. This file performs no writes.
WITH
request AS (
 SELECT :row AS r, :ctx AS c, :row -> '$.claim' AS claim,
        :row ->> '$.claim.kind' AS kind, :ctx ->> '$.action' AS action,
        :ctx ->> '$.role' AS role
),
links AS (
 SELECT g.value AS link, f.value AS fact FROM request, json_each(r, '$.grounds') g
 LEFT JOIN json_each(c, '$.records') f ON f.key = g.value ->> '$.assertion_id'
),
refs AS (
 SELECT link ->> '$.assertion_id' AS id FROM links
 UNION SELECT link ->> '$.transfer_convention' FROM links
 UNION SELECT claim ->> '$.warrant.criterion' FROM request
 UNION SELECT claim ->> '$.precedence_convention' FROM request
 UNION SELECT claim ->> '$.target' FROM request
 UNION SELECT claim ->> '$.question' FROM request
 UNION SELECT claim ->> '$.successor' FROM request
 UNION SELECT claim ->> '$.rule_version' FROM request
 UNION SELECT value FROM request, json_each(claim, '$.adjustment.ground_ids')
 UNION SELECT value ->> '$.source_version' FROM request, json_each(claim, '$.page_binding.pages')
 UNION SELECT claim ->> '$.citation.source_version' FROM request
 UNION SELECT claim ->> '$.pair.snapshot' FROM request
 UNION SELECT claim ->> '$.snapshot' FROM request
 UNION SELECT value FROM request, json_each(claim,'$.evidence_receipts')
 UNION SELECT value FROM request, json_each(claim, '$.observations')
 UNION SELECT value FROM request, json_each(claim, '$.inputs')
 UNION SELECT value FROM request, json_each(claim, '$.basis') WHERE kind='recommendation'
 UNION SELECT value FROM request, json_each(claim, '$.pair.records')
 UNION SELECT value FROM request, json_each(claim, '$.disclosed_gaps')
),
support_refs AS (
 SELECT value AS ref, 'input' AS purpose FROM request, json_each(claim,'$.inputs') WHERE kind='derived'
 UNION SELECT value, 'input' FROM request, json_each(claim,'$.basis') WHERE kind='recommendation'
 UNION SELECT value, 'context' FROM request, json_each(claim,'$.observations') WHERE kind='conflict'
),
criterion AS (
 SELECT f.value AS v FROM request, json_each(c, '$.records') f
 WHERE f.key=claim ->> '$.warrant.criterion'
   AND f.value ->> '$.kind' IN ('source','convention') AND f.value ->> '$.status'='confirmed'
   AND f.value ->> '$.stale'=0 AND f.value ->> '$.version'=claim ->> '$.warrant.criterion_version'
),
bands AS (
 SELECT b.key AS label, b.value AS band FROM criterion, json_each(v, '$.bands') b
),
required AS (SELECT value AS slot FROM request, json_each(c, '$.required_slots')),
members AS (SELECT value AS m FROM request, json_each(c, '$.snapshot.members')),
reviewed AS (
 SELECT j.value AS review FROM request, json_each(c, '$.reviews') j
 WHERE j.value ->> '$.role' = :catalog ->> '$.actions.release.qualifying_review.role'
 AND j.value ->> '$.action' IN (SELECT value FROM json_each(:catalog,'$.actions.release.qualifying_review.actions'))
 AND json_type(j.value,'$.actor')='text' AND is_canonical_id(j.value ->> '$.actor')=1
 AND j.value ->> '$.actor' <> r ->> '$.was_attributed_to'
 AND j.value ->> '$.snapshot'=claim ->> '$.pair.snapshot'
 AND j.value ->> '$.stale'=0 AND j.value ->> '$.passed'=1
),
service AS (
 SELECT request.*, a.value AS spec FROM request LEFT JOIN json_each(:catalog, '$.actions') a ON a.key=action
),
adjustment_links AS (
 SELECT link, fact FROM links WHERE link ->> '$.purpose'='adjustment'
),
valid_adjustment AS (
 SELECT 1 FROM request
 WHERE claim ->> '$.adjustment.disposition'='accepted_with_flag'
 AND claim ->> '$.adjustment.proposed'=claim ->> '$.value'
 AND EXISTS(SELECT 1 FROM adjustment_links)
 AND NOT EXISTS(SELECT value FROM json_each(claim,'$.adjustment.ground_ids') EXCEPT
                SELECT link ->> '$.assertion_id' FROM adjustment_links)
 AND NOT EXISTS(SELECT link ->> '$.assertion_id' FROM adjustment_links EXCEPT
                SELECT value FROM json_each(claim,'$.adjustment.ground_ids'))
 AND NOT EXISTS(SELECT 1 FROM adjustment_links WHERE
   (fact ->> '$.status' IS NOT 'confirmed' AND coalesce(fact ->> '$.source_eligible',0)<>1) OR fact ->> '$.stale' IS NOT 0 OR
   coalesce(fact ->> '$.state','') NOT IN ('value','no_value') OR
   NOT EXISTS(SELECT 1 FROM json_each(fact,'$.supports') WHERE value=link ->> '$.proposition'))
),
bad(code, reason) AS (
 SELECT 'C4','A reference was outside the issued packet'
 FROM request WHERE EXISTS(SELECT 1 FROM refs WHERE id IS NOT NULL AND NOT EXISTS(
 SELECT 1 FROM json_each(c,'$.packet') WHERE value=refs.id))
 UNION ALL
 SELECT 'C10','undetermined results remain unscored'
 FROM request WHERE kind='derived' AND (claim ->> '$.strength'='undetermined' AND claim ->> '$.value' IS NOT NULL)
 UNION ALL
 SELECT 'C11','Role, target status, scope or operation authority does not permit this action'
 FROM service WHERE NOT EXISTS(SELECT 1 FROM json_each(spec,'$.roles') WHERE value=role OR (value='@agent' AND c ->> '$.actor_class'='agent')) OR
 (action IN ('endorse','challenge','confirm','supersede','retract','sign_off') AND
 coalesce(c ->> '$.target.status','') NOT IN ('proposed','endorsed','confirmed','contested')) OR
 (action IN ('supersede','retract') AND role <> 'owner' AND
 (c ->> '$.target.author' IS NOT r ->> '$.was_attributed_to' OR
 (c ->> '$.target.status'='contested' AND c ->> '$.target.effect' IS NOT 'challenge'))) OR
 (action IN ('retract','supersede') AND c ->> '$.target.effect'='challenge'
 AND (action <> 'retract' OR c ->> '$.target.author' IS NOT r ->> '$.was_attributed_to')) OR
 (action='confirm' AND (c ->> '$.actor_class' IS NOT 'person' OR
 (c ->> '$.target.kind'='convention' AND role <> 'owner'))) OR
 (action='retract' AND c ->> '$.target.effect'='release' AND role <> 'owner') OR
 (action='decide' AND claim ->> '$.effect'='dismiss_challenge' AND
 (role <> 'owner' OR c ->> '$.target.effect' IS NOT 'challenge')) OR
 (action='sign_off' AND (c ->> '$.actor_class' IS NOT 'person' OR
 length(trim(coalesce(c ->> '$.engineer_name','')))=0 OR c ->> '$.target.effect' IS NOT 'release')) OR
 (action='release' AND (c ->> '$.delegation.active' IS NOT 1 OR
 c ->> '$.delegation.actor' IS NOT r ->> '$.was_attributed_to' OR
 c ->> '$.delegation.subject' IS NOT r ->> '$.subject' OR
 c ->> '$.delegation.action' IS NOT 'release')) OR
 (action='deliver_draft' AND EXISTS(SELECT value FROM json_each(c,'$.snapshot.gaps')
 EXCEPT SELECT value FROM json_each(claim,'$.disclosed_gaps'))) OR
 (kind='act' AND claim ->> '$.effect' IS NOT action) OR
 (kind='decision' AND (CASE action WHEN 'decide' THEN coalesce(claim ->> '$.effect','') NOT IN ('answer','dismiss_challenge')
 ELSE claim ->> '$.effect' IS NOT action END)) OR
 EXISTS(SELECT 1 FROM json_each(spec,'$.conditions') x WHERE x.value<>'C12' AND
 NOT EXISTS(SELECT 1 FROM json_each(c,'$.satisfied_authority_conditions') y WHERE y.value=x.value))
 UNION ALL
 SELECT 'C12','Formal release needs every confirmed output reviewed on the exact eligible frozen pair'
 FROM request WHERE action='release' AND (
 c ->> '$.required_list_owner_confirmed' IS NOT 1 OR
 c ->> '$.scope_id' IS NOT claim ->> '$.target' OR NOT EXISTS(SELECT 1 FROM required)
 OR c ->> '$.snapshot.id' IS NOT claim ->> '$.pair.snapshot'
 OR c ->> '$.snapshot.word_sha256' IS NOT claim ->> '$.pair.word_sha256'
 OR c ->> '$.snapshot.excel_sha256' IS NOT claim ->> '$.pair.excel_sha256'
 OR EXISTS(SELECT m ->> '$.id' FROM members EXCEPT SELECT value FROM json_each(claim,'$.pair.records'))
 OR EXISTS(SELECT value FROM json_each(claim,'$.pair.records') EXCEPT SELECT m ->> '$.id' FROM members)
 OR EXISTS(SELECT 1 FROM members WHERE m ->> '$.stale' IS NOT 0 OR m ->> '$.open_grade_questions' IS NOT 0
 OR (m ->> '$.status' IS NOT 'confirmed' AND (m ->> '$.status' IS NOT 'endorsed' OR NOT EXISTS(
 SELECT 1 FROM json_each(:catalog,'$.endorsement_suffices_for') WHERE value=m ->> '$.kind')))
 OR NOT EXISTS(SELECT 1 FROM reviewed WHERE review ->> '$.record'=m ->> '$.id'
 AND json_type(m,'$.producer')='text' AND is_canonical_id(m ->> '$.producer')=1
 AND review ->> '$.actor' <> m ->> '$.producer'
 AND (m ->> '$.status'='confirmed' OR review ->> '$.action'='endorse'))))
)
SELECT DISTINCT code,reason FROM bad ORDER BY code;
