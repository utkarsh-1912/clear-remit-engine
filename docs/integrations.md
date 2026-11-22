# ClearRemit connector setup

**Integrations** in the sidebar shows configured capabilities, accepted provider events, and invoice email attempts for the selected entity. Configured status means credentials are present. Verify connectivity and provider behavior in the relevant sandbox before production use.

## Bank, remittance, and ERP bridges

Set `CLEARREMIT_CONNECTORS_JSON` in the server environment. Each entity can have a different bearer secret for each bridge. Use distinct random secrets of at least 24 characters. The Stripe value is the signing secret supplied by that webhook endpoint.

```json
{
  "ENTITY_ID": {
    "bank": "BANK_BEARER_SECRET_FROM_DEPLOYMENT",
    "remittance": "REMITTANCE_BEARER_SECRET_FROM_DEPLOYMENT",
    "erp": "ERP_BEARER_SECRET_FROM_DEPLOYMENT",
    "stripe": "STRIPE_WEBHOOK_SIGNING_SECRET"
  }
}
```

| Method and path, relative to `/api/connector-hooks/{entity_id}` | Provider workflow |
| --- | --- |
| `POST /bank` | Submit the same JSON payload as `POST /api/runs`. Use a stable UUID for `submission_id` across retries. Include statement contents and an opening ledger or set `use_registered_ledger` to true. |
| `POST /remittance` | Submit `external_id`, `customer_id`, and `detail`. Use the provider's immutable message ID so repeat deliveries return the same case. |
| `GET /erp` | Poll for approved, prepared export batches. |
| `GET /erp/{batch_id}` | Download the immutable CSV or XML. The ERP-side job should deduplicate on the batch UUID before posting. |
| `POST /erp/{batch_id}/receipt` | Return `version`, `status` set to `confirmed` or `rejected`, and the ERP receipt or error in `receipt`. Repeat an identical acknowledgment safely. |

Use `Authorization: Bearer <secret>` with these routes. ClearRemit runs matching on incoming bank data. The bank, mailbox, or ERP middleware is responsible for polling its source system, converting its payload where needed, and calling the bridge. No operator login is needed for bridge calls.

## Stripe

Configure Stripe to send `payment_intent.succeeded` to `/api/connector-hooks/{entity_id}/stripe`. Set `clearremit_invoice_id` in the PaymentIntent metadata to the issued invoice's internal UUID. ClearRemit verifies the signature on the original request bytes, enforces a five-minute timestamp tolerance, and records one case per PaymentIntent. Reconcile the bank settlement and confirm the export receipt to change the invoice balance. Stripe checkout creation and refunds require additional work. [Stripe webhook signatures](https://docs.stripe.com/webhooks/signature)

## Invoice email

Set `CLEARREMIT_SMTP_HOST`, `CLEARREMIT_SMTP_PORT` (defaults to 465), and `CLEARREMIT_SMTP_FROM`. If the server requires authentication, set `CLEARREMIT_SMTP_USERNAME` and `CLEARREMIT_SMTP_PASSWORD`. Use an implicit-TLS SMTP endpoint. Operators can send an issued invoice from the register to the customer's billing email. **Accepted** indicates the SMTP server accepted the message. **Unverified** or **sending** after an interrupted request requires checking the provider before resending. [Python SMTP over TLS](https://docs.python.org/3/library/smtplib.html#smtplib.SMTP_SSL)

## SSO through an identity proxy

Deploy an identity-aware reverse proxy configured with your OIDC provider. After authenticating and validating the user's identity, have the proxy overwrite `X-ClearRemit-Identity` with a stable identifier and set `X-ClearRemit-Proxy-Key` to the secret shared with ClearRemit via `CLEARREMIT_SSO_PROXY_SECRET`. Strip client-supplied values for both headers at the edge, and restrict direct access to the application origin. Set each authorized operator's `sso_subject` to the corresponding identifier in `CLEARREMIT_USERS_JSON`, along with their role and memberships. [OpenID Connect ID token validation](https://openid.net/specs/openid-connect-core-1_0.html#IDTokenValidation)

## Provider work remaining

Direct bank and mailbox OAuth onboarding, vendor-native ERP posting, online checkout and refunds, and statutory e-invoicing adapters still need provider-specific implementation and sandbox verification. The bridges support external jobs that already have provider access.
