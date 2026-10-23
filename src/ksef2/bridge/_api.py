"""What the manifest says about each public sync class and each member it leaves out.

The classes of ``ksef2.clients`` are discovered at runtime, so this table only
records what introspection cannot know: how a class is reached, which state a
live object carries, which item type a pager holds and why a member is not an
operation. A public class or member missing from both the table and the manifest
is a bug the unit tests report.
"""

from dataclasses import dataclass

from pydantic import BaseModel

from ksef2._domain.models.auth import AuthenticationResumeState
from ksef2._domain.models.batch import BatchSessionResumeState
from ksef2._domain.models.certificates import CertificateEnrollmentResumeState
from ksef2._domain.models.invoices import (
    ExportResumeState,
    InvoiceSubmissionResumeState,
)
from ksef2._domain.models.invoices import InvoiceMetadata
from ksef2._domain.models.permissions import PermissionOperationResumeState
from ksef2._domain.models.session import OnlineSessionResumeState
from ksef2._domain.models.tokens import GeneratedTokenResumeState
from ksef2.bridge._data_models import ExportedInvoices as ExportedInvoicesData
from ksef2.clients import (
    AuthClient,
    AuthenticatedClient,
    BatchService,
    BatchSessionClient,
    CertificateEnrollment,
    CertificatesClient,
    Client,
    CollectiveIdentifiersClient,
    EncryptionClient,
    ExportedInvoices,
    ExportJob,
    GeneratedToken,
    InvoiceSearchPager,
    InvoiceSessionsClient,
    InvoiceSubmission,
    InvoicesService,
    LimitsClient,
    OnlineSessionClient,
    OperationHandle,
    Pager,
    PeppolClient,
    PermissionOperation,
    PermissionsClient,
    SessionManagementClient,
    TemporalTestData,
    TestDataClient,
    TokensClient,
)

ROOT_STATE = "unauthenticated"
"""Client that needs no KSeF token."""
AUTHENTICATED_STATE = "authenticated"
"""Client reached through a live authentication."""
ONLINE_SESSION_STATE = "online_session"
"""Operations inside one online session."""
BATCH_SESSION_STATE = "batch_session"
"""Operations inside one batch session."""
HANDLE_STATE = "handle"
"""One operation KSeF finishes asynchronously."""
PAGER_STATE = "pager"
"""Walk over one collection."""
RESULT_STATE = "result"
"""Plain result data the SDK assembled."""

KIND_ROOT = "root"
KIND_CLIENT = "client"
KIND_SERVICE = "service"
KIND_SESSION = "session"
KIND_HANDLE = "handle"
KIND_PAGER = "pager"
KIND_RESULT = "result"

REASON_DEPRECATED = "deprecated"
"""PEP 702 ``@deprecated`` marks the member for removal."""
REASON_ABSTRACT = "abstract"
"""The member is an abstract hook with no bindable behaviour."""
REASON_BRANCH = "branch_accessor"
"""The member only returns another unit the manifest already describes."""
REASON_ITERATOR = "python_iterator"
"""The member yields Python objects instead of returning data."""
REASON_LIFECYCLE = "lifecycle"
"""The member manages the local object rather than calling KSeF."""
REASON_LOCAL_FILESYSTEM = "local_filesystem"
"""The member reads or writes files on the machine running the SDK."""
REASON_SENSITIVE = "sensitive"
"""The member is a second path to a secret the manifest already carries."""
REASON_PYTHON_ONLY = "python_only"
"""The member takes or returns a type that has no JSON Schema."""

REASONS: frozenset[str] = frozenset(
    {
        REASON_ABSTRACT,
        REASON_BRANCH,
        REASON_DEPRECATED,
        REASON_ITERATOR,
        REASON_LIFECYCLE,
        REASON_LOCAL_FILESYSTEM,
        REASON_PYTHON_ONLY,
        REASON_SENSITIVE,
    }
)
"""Every reason an ``excluded`` entry may carry."""

STATES: tuple[tuple[str, str], ...] = (
    (
        ROOT_STATE,
        "Reached from a root client with no KSeF token: the root client itself,"
        " the authentication branch and the branches that need only an environment.",
    ),
    (
        AUTHENTICATED_STATE,
        "Needs a live authentication. In Python the authenticated client carries"
        " the bearer token; the state that rebuilds it is AuthenticationResumeState.",
    ),
    (
        ONLINE_SESSION_STATE,
        "Runs inside one online session, which OnlineSessionResumeState identifies.",
    ),
    (
        BATCH_SESSION_STATE,
        "Runs inside one batch session, which BatchSessionResumeState identifies.",
    ),
    (
        HANDLE_STATE,
        "Refers to one operation KSeF finishes asynchronously. The handle's"
        " resume-state model carries the reference number it polls.",
    ),
    (
        PAGER_STATE,
        "Walks one collection. Each page carries an opaque cursor a later call,"
        " another process or another language binding hands back to continue.",
    ),
    (
        RESULT_STATE,
        "Plain data the SDK assembled for you, such as a decrypted invoice export.",
    ),
)

CONVENTIONS: tuple[tuple[str, str], ...] = (
    (
        "schemas",
        "Every schema is JSON Schema 2020-12. Each named Python type, including"
        " every Literal alias, is written once in `$defs` and pointed at with a"
        " local `$ref`, so a generator emits one named type per definition.",
    ),
    (
        "bytes",
        "Python bytes travel as base64 encoded strings. Their schema carries"
        ' `contentEncoding: "base64"` and never `format: "binary"`.',
    ),
    (
        "paths",
        'A `pathlib.Path` value is a string with `format: "path"` that names a'
        " file on the machine running the SDK.",
    ),
    (
        "defaults",
        "A parameter's `default` is the JSON value pydantic records for it, and"
        " `required` follows the Python signature.",
    ),
    (
        "state",
        "An operation whose unit declares `receiver_state` needs that state to"
        " run. The Python client holds it silently, so the manifest lists it as a"
        ' parameter named `state` with `origin: "unit_state"` and the resume-state'
        ' schema. `origin: "signature"` marks a parameter of the Python method.',
    ),
    (
        "live_objects",
        "Sessions, handles, pagers and export results are described by data. An"
        " operation that returns one names its unit and gives the schema of the"
        " state, page or data model that carries it.",
    ),
    (
        "cursors",
        "A paged operation returns the items of one page and the opaque"
        " `next_cursor` that resumes the collection after it; a null cursor ends"
        " the walk. Keep a cursor as a string: it is versioned SDK state.",
    ),
    (
        "docs",
        "Each `summary` and each parameter `description` comes from the Python"
        " docstring, which stays the source of the human API reference.",
    ),
    (
        "secrets",
        "Fields that hold credentials are ordinary strings in these schemas, and"
        " the manifest itself carries no secret value. Treat a field named token,"
        " key, secret or password as a credential wherever it is stored.",
    ),
)


@dataclass(frozen=True)
class Accessor:
    """How the public API reaches a class.

    Attributes:
        unit: Identifier of the unit that exposes it.
        member: Name of the property or method that returns it.
    """

    unit: str
    member: str


@dataclass(frozen=True)
class Unit:
    """One public sync class of ``ksef2.clients``.

    Attributes:
        id: Stable namespace of its operation identifiers.
        cls: The class itself.
        kind: What kind of object it is.
        state: State its operations run on.
        accessors: Members that return it.
        receiver_state: Model that carries the state of a live object of this
            unit, or ``None`` when the object holds no state to carry.
        item_model: Item type of a pager whose generic parameter this class
            fixes, or ``None`` when the item type stays open.
        data_model: Model that describes an object of this unit as data.
    """

    id: str
    cls: type[object]
    kind: str
    state: str
    accessors: tuple[Accessor, ...] = ()
    receiver_state: type[BaseModel] | None = None
    item_model: type[object] | None = None
    data_model: type[BaseModel] | None = None


@dataclass(frozen=True)
class Exclusion:
    """Why a public member is not an operation.

    Attributes:
        reason: Machine-readable reason, one of the ``REASON_*`` values.
        detail: Sentence that tells a reader what to use instead.
    """

    reason: str
    detail: str


def _pager_pages_detail(unit: str) -> str:
    """Return the exclusion note for the page iterator of a pager.

    Args:
        unit: Identifier of the pager unit.

    Returns:
        The detail of its ``pages()`` exclusion.
    """
    return (
        f"{unit}.pages() yields Python lists of items rather than returning one"
        f" page. {unit}.page(cursor) returns a Page with the items and the"
        " cursor that resumes the collection after them."
    )


UNITS: tuple[Unit, ...] = (
    Unit(
        id="client",
        cls=Client,
        kind=KIND_ROOT,
        state=ROOT_STATE,
    ),
    Unit(
        id="auth",
        cls=AuthClient,
        kind=KIND_CLIENT,
        state=ROOT_STATE,
        accessors=(Accessor("client", "authentication"),),
    ),
    Unit(
        id="authenticated",
        cls=AuthenticatedClient,
        kind=KIND_CLIENT,
        state=AUTHENTICATED_STATE,
        receiver_state=AuthenticationResumeState,
    ),
    Unit(
        id="tokens",
        cls=TokensClient,
        kind=KIND_CLIENT,
        state=AUTHENTICATED_STATE,
        accessors=(Accessor("authenticated", "tokens"),),
    ),
    Unit(
        id="permissions",
        cls=PermissionsClient,
        kind=KIND_CLIENT,
        state=AUTHENTICATED_STATE,
        accessors=(Accessor("authenticated", "permissions"),),
    ),
    Unit(
        id="certificates",
        cls=CertificatesClient,
        kind=KIND_CLIENT,
        state=AUTHENTICATED_STATE,
        accessors=(Accessor("authenticated", "certificates"),),
    ),
    Unit(
        id="collective_identifiers",
        cls=CollectiveIdentifiersClient,
        kind=KIND_CLIENT,
        state=AUTHENTICATED_STATE,
        accessors=(Accessor("authenticated", "collective_identifiers"),),
    ),
    Unit(
        id="encryption",
        cls=EncryptionClient,
        kind=KIND_CLIENT,
        state=ROOT_STATE,
        accessors=(Accessor("client", "encryption"),),
    ),
    Unit(
        id="export_job",
        cls=ExportJob,
        kind=KIND_HANDLE,
        state=HANDLE_STATE,
        receiver_state=ExportResumeState,
    ),
    Unit(
        id="exported_invoices",
        cls=ExportedInvoices,
        kind=KIND_RESULT,
        state=RESULT_STATE,
        data_model=ExportedInvoicesData,
    ),
    Unit(
        id="generated_token",
        cls=GeneratedToken,
        kind=KIND_HANDLE,
        state=HANDLE_STATE,
        receiver_state=GeneratedTokenResumeState,
    ),
    Unit(
        id="certificate_enrollment",
        cls=CertificateEnrollment,
        kind=KIND_HANDLE,
        state=HANDLE_STATE,
        receiver_state=CertificateEnrollmentResumeState,
    ),
    Unit(
        id="invoice_search_pager",
        cls=InvoiceSearchPager,
        kind=KIND_PAGER,
        state=PAGER_STATE,
        item_model=InvoiceMetadata,
    ),
    Unit(
        id="invoice_sessions",
        cls=InvoiceSessionsClient,
        kind=KIND_CLIENT,
        state=AUTHENTICATED_STATE,
        accessors=(Accessor("authenticated", "invoice_sessions"),),
    ),
    Unit(
        id="invoice_submission",
        cls=InvoiceSubmission,
        kind=KIND_HANDLE,
        state=HANDLE_STATE,
        receiver_state=InvoiceSubmissionResumeState,
    ),
    Unit(
        id="invoices",
        cls=InvoicesService,
        kind=KIND_SERVICE,
        state=AUTHENTICATED_STATE,
        accessors=(Accessor("authenticated", "invoices"),),
    ),
    Unit(
        id="batch",
        cls=BatchService,
        kind=KIND_SERVICE,
        state=AUTHENTICATED_STATE,
        accessors=(Accessor("authenticated", "batch"),),
    ),
    Unit(
        id="batch_session",
        cls=BatchSessionClient,
        kind=KIND_SESSION,
        state=BATCH_SESSION_STATE,
        receiver_state=BatchSessionResumeState,
    ),
    Unit(
        id="limits",
        cls=LimitsClient,
        kind=KIND_CLIENT,
        state=AUTHENTICATED_STATE,
        accessors=(Accessor("authenticated", "limits"),),
    ),
    Unit(
        id="online_session",
        cls=OnlineSessionClient,
        kind=KIND_SESSION,
        state=ONLINE_SESSION_STATE,
        receiver_state=OnlineSessionResumeState,
    ),
    Unit(
        id="pager",
        cls=Pager,
        kind=KIND_PAGER,
        state=PAGER_STATE,
    ),
    Unit(
        id="handle",
        cls=OperationHandle,
        kind=KIND_HANDLE,
        state=HANDLE_STATE,
    ),
    Unit(
        id="peppol",
        cls=PeppolClient,
        kind=KIND_CLIENT,
        state=ROOT_STATE,
        accessors=(Accessor("client", "peppol"),),
    ),
    Unit(
        id="permission_operation",
        cls=PermissionOperation,
        kind=KIND_HANDLE,
        state=HANDLE_STATE,
        receiver_state=PermissionOperationResumeState,
    ),
    Unit(
        id="sessions",
        cls=SessionManagementClient,
        kind=KIND_CLIENT,
        state=AUTHENTICATED_STATE,
        accessors=(Accessor("authenticated", "sessions"),),
    ),
    Unit(
        id="testdata",
        cls=TestDataClient,
        kind=KIND_CLIENT,
        state=AUTHENTICATED_STATE,
        accessors=(
            Accessor("authenticated", "testdata"),
            Accessor("client", "testdata"),
        ),
    ),
    Unit(
        id="temporal_test_data",
        cls=TemporalTestData,
        kind=KIND_CLIENT,
        state=AUTHENTICATED_STATE,
        accessors=(Accessor("testdata", "temporal"),),
    ),
)

EXCLUSIONS: dict[str, dict[str, Exclusion]] = {
    "auth": {
        "with_xades": Exclusion(
            REASON_PYTHON_ONLY,
            "Takes a loaded cryptography certificate and private key, or an"
            " XAdESCredentials holder, and neither has a JSON Schema. Authenticate"
            " with auth.with_token, auth.with_profile or auth.with_test_certificate,"
            " which take text, or sign the challenge in the host language.",
        )
    },
    "authenticated": {
        "raw": Exclusion(
            REASON_PYTHON_ONLY,
            "Returns the low-level endpoint facade, which is a Python object graph"
            " over httpx rather than data. Its calls stay in Python.",
        )
    },
    "batch": {
        "upload_parts": Exclusion(
            REASON_PYTHON_ONLY,
            "Takes the live batch session whose upload instructions it posts. Call"
            " batch_session.upload_parts with that session's resume state instead.",
        )
    },
    "client": {
        "close": Exclusion(
            REASON_LIFECYCLE,
            "Closes the local HTTP transport and refuses further use of the client."
            " It sends no KSeF request, so a generated binding owns it as a"
            " destructor rather than as an operation.",
        ),
        "raw": Exclusion(
            REASON_PYTHON_ONLY,
            "Returns the low-level endpoint facade, which is a Python object graph"
            " over httpx rather than data. Its calls stay in Python.",
        ),
    },
    "exported_invoices": {
        "invoices": Exclusion(
            REASON_ITERATOR,
            "Yields ``(ksef_number, xml)`` pairs through Python iteration. The same"
            " bytes are inside the `archive` data model, so a binding can read the"
            " archive entries itself.",
        ),
        "save": Exclusion(
            REASON_LOCAL_FILESYSTEM,
            "Extracts the archive into a directory on the machine running the SDK"
            " and returns pathlib paths. Write the files from `archive` instead.",
        ),
    },
    "generated_token": {
        "to_sensitive_dict": Exclusion(
            REASON_SENSITIVE,
            "Exports the one-time token through an untyped mapping for deliberately"
            " protected persistence. The `token` attribute carries the same value"
            " as a string, so a binding needs no second path to the secret.",
        )
    },
    "handle": {
        "get_status": Exclusion(
            REASON_ABSTRACT,
            "Abstract hook of the handle base class, whose status and result type"
            " parameters are unresolved. Each concrete handle unit describes its own"
            " get_status.",
        )
    },
    "invoice_search_pager": {
        "pages": Exclusion(
            REASON_ITERATOR, _pager_pages_detail("invoice_search_pager")
        ),
        "responses": Exclusion(
            REASON_ITERATOR,
            "Yields every QueryInvoicesMetadataResponse of the search through Python"
            " iteration. first_response() reads one response and page(cursor)"
            " resumes the search after any page.",
        ),
    },
    "pager": {"pages": Exclusion(REASON_ITERATOR, _pager_pages_detail("pager"))},
    "testdata": {
        "temporal": Exclusion(
            REASON_BRANCH,
            "Returns the temporal test-data client, which the temporal_test_data"
            " unit already describes.",
        )
    },
}
