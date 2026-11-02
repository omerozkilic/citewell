# On-call Handbook

This handbook describes how the platform team at Defne Yazılım runs its on-call rotation.

## Rotation

The rotation is one week long and hands over every Monday at 11:00 Istanbul time. Each rotation has a
primary and a secondary engineer. Engineers are on call at most once every four weeks.

## Response Times

Severity 1 incidents (customer-facing outage) must be acknowledged within 5 minutes and a status page
update must be published within 15 minutes. Severity 2 incidents must be acknowledged within 30 minutes.
Severity 3 issues are handled during business hours.

## Compensation

Each on-call week is compensated with a flat payment and one extra day off, which must be used within
the following 60 days.

## Post-incident Reviews

Every Severity 1 incident gets a blameless post-incident review within 5 business days. Action items
from the review are tracked in the issue tracker with the label `incident-followup`.
