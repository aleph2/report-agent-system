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
readings AS (SELECT value AS outcome FROM request, json_each(c, '$.applicable_readings')),
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
authorized_adjustments AS (
 SELECT a.value AS rule FROM request, json_each(c,'$.permitted_adjustments') a
 WHERE a.value ->> '$.criterion'=claim ->> '$.warrant.criterion' AND a.value ->> '$.subject'=r ->> '$.subject'
 AND a.value ->> '$.effective_value'=claim ->> '$.value'
 AND NOT EXISTS(SELECT value FROM json_each(a.value,'$.support_ids') EXCEPT
                SELECT link ->> '$.assertion_id' FROM adjustment_links)
 AND NOT EXISTS(SELECT link ->> '$.assertion_id' FROM adjustment_links EXCEPT
                SELECT value FROM json_each(a.value,'$.support_ids'))
),
valid_adjustment AS (
 SELECT 1 FROM request
 WHERE claim ->> '$.adjustment.disposition'='accepted_with_flag'
 AND claim ->> '$.adjustment.proposed'=claim ->> '$.value'
 AND EXISTS(SELECT 1 FROM adjustment_links) AND EXISTS(SELECT 1 FROM authorized_adjustments)
 AND NOT EXISTS(SELECT value FROM json_each(claim,'$.adjustment.ground_ids') EXCEPT
                SELECT link ->> '$.assertion_id' FROM adjustment_links)
 AND NOT EXISTS(SELECT link ->> '$.assertion_id' FROM adjustment_links EXCEPT
                SELECT value FROM json_each(claim,'$.adjustment.ground_ids'))
 AND NOT EXISTS(SELECT 1 FROM adjustment_links WHERE
   fact ->> '$.status' IS NOT 'confirmed' OR fact ->> '$.stale' IS NOT 0 OR
   coalesce(fact ->> '$.state','') NOT IN ('value','no_value') OR
   NOT EXISTS(SELECT 1 FROM json_each(fact,'$.supports') WHERE value=link ->> '$.proposition'))
),
bad(code, reason) AS (
 SELECT 'C1', 'Use the catalog action that produces this kind'
 FROM service WHERE kind IS NOT spec ->> '$.kind'
 UNION ALL
 SELECT 'C2', 'Explicit absence needs its own quoted source and stated coverage'
 FROM request WHERE kind='source' AND claim ->> '$.state'='no_value'
 AND (length(trim(coalesce(claim ->> '$.citation.quote','')))=0 OR length(trim(coalesce(claim ->> '$.coverage','')))=0)
 UNION ALL
 SELECT 'C3','Direct evidence needs applicable confirmed, current observations bound to the classification'
 FROM request WHERE kind='judgment' AND claim ->> '$.basis'='evidence' AND (
 NOT EXISTS(SELECT 1 FROM links WHERE link ->> '$.purpose'='classification') OR
 EXISTS(SELECT 1 FROM links WHERE link ->> '$.purpose'='classification' AND
 (fact ->> '$.status' IS NOT 'confirmed' OR fact ->> '$.stale' IS NOT 0 OR
  coalesce(fact ->> '$.state','') NOT IN ('value','no_value') OR
  NOT EXISTS(SELECT 1 FROM json_each(fact,'$.supports') WHERE value=link ->> '$.proposition'))))
 UNION ALL
 SELECT 'C4','A reference was outside the issued packet'
 FROM request WHERE EXISTS(SELECT 1 FROM refs WHERE id IS NOT NULL AND NOT EXISTS(
 SELECT 1 FROM json_each(c,'$.packet') WHERE value=refs.id))
 UNION ALL
 SELECT 'C5','Cross-subject support needs a current confirmed transfer with matching scope'
 FROM request WHERE EXISTS(
 SELECT 1 FROM support_refs s LEFT JOIN json_each(c,'$.records') f ON f.key=s.ref
 WHERE f.value ->> '$.subject' IS NOT r ->> '$.subject' AND NOT EXISTS(
 SELECT 1 FROM links WHERE link ->> '$.assertion_id'=s.ref AND link ->> '$.purpose'=s.purpose
 AND link ->> '$.transfer_convention' IS NOT NULL)) OR
 EXISTS(SELECT 1 FROM links WHERE fact ->> '$.subject' IS NOT r ->> '$.subject'
 AND NOT EXISTS(SELECT 1 FROM json_each(c,'$.records') t WHERE t.key=link ->> '$.transfer_convention'
 AND t.value ->> '$.kind'='convention' AND t.value ->> '$.status'='confirmed' AND t.value ->> '$.stale'=0
 AND t.value ->> '$.from'=fact ->> '$.subject' AND t.value ->> '$.to'=r ->> '$.subject'
 AND t.value ->> '$.proposition'=link ->> '$.proposition'))
 UNION ALL
 SELECT 'C6','Select a confirmed versioned criterion and its permitted classification and value'
 FROM request WHERE kind='judgment' AND (NOT EXISTS(SELECT 1 FROM criterion) OR
 EXISTS(SELECT 1 FROM json_each(claim,'$.alternatives') alt WHERE NOT EXISTS(SELECT 1 FROM bands WHERE label=alt.value)) OR
 (claim ->> '$.classification' IS NOT NULL AND NOT EXISTS(SELECT 1 FROM bands WHERE label=claim ->> '$.classification'
 AND (claim ->> '$.value' IS NULL OR decimal_between(claim ->> '$.value', band ->> '$.min', band ->> '$.max')=1))))
 UNION ALL
 SELECT 'C6','Retain the effective midpoint unless the directional adjustment has specifically entitled grounds'
 FROM request, bands, criterion
 WHERE kind='judgment' AND claim ->> '$.value' IS NOT NULL AND label=claim ->> '$.classification' AND (
 coalesce(v ->> '$.value_policy','') NOT IN ('criterion_range','confirmed_midpoint') OR
 (v ->> '$.value_policy'='confirmed_midpoint' AND (band ->> '$.midpoint' IS NULL OR
 (decimal_between(claim ->> '$.value',band ->> '$.midpoint',band ->> '$.midpoint')=0
 AND NOT EXISTS(SELECT 1 FROM valid_adjustment)))))
 UNION ALL
 SELECT 'C7','Record the unresolved alternatives when applicable readings differ or cannot be exhausted'
 FROM request WHERE kind='judgment' AND (
 (claim ->> '$.basis'='evidence' AND
 (c ->> '$.readings_exhaustive' IS NOT 1 OR NOT EXISTS(SELECT 1 FROM readings) OR
 EXISTS(SELECT 1 FROM readings WHERE outcome IS NOT claim ->> '$.classification')))
 OR (claim ->> '$.basis'='assumption' AND (SELECT count(DISTINCT outcome) FROM readings)>1))
 UNION ALL
 SELECT 'C8','Identify what could overturn this assumption'
 FROM request WHERE kind='judgment' AND claim ->> '$.basis'='assumption' AND coalesce(json_array_length(claim,'$.defeaters'),0)=0
 UNION ALL
 SELECT 'C9','Resolve conflicting grounds through the confirmed precedence before claiming evidence'
 FROM request WHERE kind='judgment' AND claim ->> '$.basis'='evidence' AND EXISTS (
 SELECT 1 FROM links, json_each(fact,'$.conflicts') conflict WHERE NOT EXISTS (
 SELECT 1 FROM json_each(c,'$.records') p WHERE p.key=conflict.value ->> '$.precedence'
 AND p.value ->> '$.kind'='convention' AND p.value ->> '$.status'='confirmed' AND p.value ->> '$.stale'=0
 AND p.value ->> '$.resolves'=conflict.value ->> '$.id' AND p.value ->> '$.preferred'=link ->> '$.assertion_id'))
 UNION ALL
 SELECT 'C10','Derived strength cannot exceed any input; undetermined results remain unscored'
 FROM request WHERE kind='derived' AND ((claim ->> '$.strength'='undetermined' AND claim ->> '$.value' IS NOT NULL)
 OR EXISTS(SELECT 1 FROM json_each(claim,'$.inputs') i LEFT JOIN json_each(c,'$.records') f ON f.key=i.value
 WHERE coalesce(f.value ->> '$.strength_rank',-1)<CASE claim ->> '$.strength'
 WHEN 'determined' THEN 2 WHEN 'provisional' THEN 1 ELSE 0 END))
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
 OR EXISTS(SELECT slot FROM required EXCEPT SELECT m ->> '$.slot' FROM members)
 OR EXISTS(SELECT m ->> '$.slot' FROM members GROUP BY 1 HAVING count(*)<>1)
 OR EXISTS(SELECT m ->> '$.id' FROM members GROUP BY 1 HAVING count(*)<>1)
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
