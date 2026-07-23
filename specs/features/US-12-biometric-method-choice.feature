Feature: Choice of biometric check-in method (US-12)
  Face, fingerprint, and iris are separate kiosk options that share one
  liveness-then-match pipeline and one status outcome model.

  Background:
    Given tenant "acme" with kiosk site "hq-lobby"
    And a registered visitor "priya" with consented enrollment for face, fingerprint, and iris

  Scenario Outline: Successful biometric check-in via any modality
    Given "priya" has a visit in status "Registered" within its visit window
    When she checks in at the kiosk using "<modality>"
    Then liveness is evaluated before matching
    And the visit status becomes "CheckedIn"
    And the audit event "visit.checked_in" records verification_method "<modality>"
    And no raw "<modality>" capture exists in any store after the capture window

    Examples:
      | modality    |
      | face        |
      | fingerprint |
      | iris        |

  Scenario: Uncertain match routes to Held, never auto-Denied
    Given "priya" has a visit in status "Registered"
    When a "fingerprint" check-in returns a below-threshold match score
    Then the visit status is "Held"
    And the visit status is NOT "Denied"
    And an audit event "visit.held" exists with hold_reason and evidence_ref
    And only a user with permission "approve_deny_holds" can transition the visit out of "Held"

  Scenario: Device failure falls back to manual verification
    Given "priya" has a visit in status "Registered"
    When the "iris" device reports failure code "CAPTURE_TIMEOUT"
    Then the kiosk offers manual verification by an officer
    And a completed manual verification transitions the visit to "CheckedIn"
    And the audit event records verification_method "manual_fallback" with the officer as actor

  Scenario: Consent is required before capture
    Given a visitor with no biometric consent on record
    When a "face" check-in is attempted
    Then no capture occurs
    And the kiosk offers QR, OTP, or manual check-in instead
