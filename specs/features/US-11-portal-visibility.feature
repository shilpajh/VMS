Feature: Website pre-registration visibility (US-11)
  A visitor's portal submission is visible the moment it is submitted,
  and transitions on the host's decision — with tenant isolation and audit.

  Background:
    Given tenant "acme" and tenant "globex" exist
    And host "rahul@acme" belongs to tenant "acme"

  Scenario: Portal submission is visible immediately as Requested
    When a visitor submits the public portal form for tenant "acme" naming host "rahul@acme"
    Then a visit record exists in tenant "acme" with status "Requested"
    And the visitor receives a tracking reference matching "REQ-\d+"
    And the record appears in tenant "acme" live visitor list within 2 seconds
    And an audit event "visit.requested" exists with correlation_id

  Scenario: Cross-tenant isolation of portal submissions
    Given a visit in tenant "acme" with status "Requested"
    When any user of tenant "globex" queries the live visitor list
    Then the "acme" visit is NOT present in the response
    When any user of tenant "globex" requests the visit record by id
    Then the response status is 403

  Scenario: Host approval issues a code
    Given a visit in tenant "acme" with status "Requested"
    When host "rahul@acme" approves it
    Then the visit status is "Registered"
    And a check-in code is issued and dispatched to the visitor's contact channel
    And an audit event "visit.registered" exists with actor "rahul@acme" and policy_version

  Scenario: Host denial is recorded with reason
    Given a visit in tenant "acme" with status "Requested"
    When host "rahul@acme" denies it with reason "unknown visitor"
    Then the visit status is "Denied"
    And no active credential exists for the visit
    And an audit event "visit.denied" exists with actor "rahul@acme" and reason "unknown visitor"

  Scenario: Invalid transition is rejected by the domain layer
    Given a visit in tenant "acme" with status "Requested"
    When a direct transition to "CheckedIn" is attempted via the API
    Then the response status is 409
    And the visit status is still "Requested"
