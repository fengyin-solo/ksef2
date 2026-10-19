"""Which public sync classes the manifest walks, and how each one maps to JSON.

The classes are the public facade's own, imported from ``ksef2.clients``. Every
method and property they expose becomes an operation, or an exclusion with a
reason, and each class says which saved state a caller needs before it can
reach one of those members.
"""

from dataclasses import dataclass
from typing import Final, cast

from pydantic import BaseModel

from ksef2.bridge._introspect import (
    module_of,
    original_bases,
    type_args,
    type_origin,
    type_parameters,
)
from ksef2.clients import AuthenticatedClient
from ksef2.clients import AuthClient
from ksef2.clients import BatchService
from ksef2.clients import BatchSessionClient
from ksef2.clients import CertificatesClient
from ksef2.clients import CertificateEnrollment
from ksef2.clients import Client
from ksef2.clients import CollectiveIdentifiersClient
from ksef2.clients import EncryptionClient
from ksef2.clients import ExportedInvoices
from ksef2.clients import ExportJob
from ksef2.clients import GeneratedToken
from ksef2.clients import InvoiceSearchPager
from ksef2.clients import InvoiceSessionsClient
from ksef2.clients import InvoiceSubmission
from ksef2.clients import InvoicesService
from ksef2.clients import LimitsClient
from ksef2.clients import OnlineSessionClient
from ksef2.clients import Pager
from ksef2.clients import PeppolClient
from ksef2.clients import PermissionOperation
from ksef2.clients import PermissionsClient
from ksef2.clients import SessionManagementClient
from ksef2.clients import TemporalTestData
from ksef2.clients import TestDataClient
from ksef2.clients import TokensClient
from ksef2.models import AuthenticationResumeState
from ksef2.models import BatchSessionResumeState
from ksef2.models import CertificateEnrollmentResumeState
from ksef2.models import ExportedInvoicesData
from ksef2.models import ExportResumeState
from ksef2.models import GeneratedTokenResumeState
from ksef2.models import InvoiceSubmissionResumeState
from ksef2.models import OnlineSessionResumeState
from ksef2.models import PermissionOperationResumeState

#: Receivers named in the manifest. A receiver says which object the call needs
#: in hand, and ``state_schema`` says which saved model rebuilds that object.
RECEIVER_UNAUTHENTICATED: Final = "unauthenticated"
RECEIVER_AUTHENTICATED: Final = "authenticated"
RECEIVER_ONLINE_SESSION: Final = "online_session"
RECEIVER_BATCH_SESSION: Final = "batch_session"
RECEIVER_HANDLE: Final = "handle"

#: Modules whose classes are clients rather than data. A member that hands back
#: one of them is an accessor, and its methods are operations of their own.
CLIENT_MODULES: Final[tuple[str, ...]] = (
    "ksef2._clients",
    "ksef2._services",
    "ksef2.raw",
)


@dataclass(frozen=True)
class WalkedClass:
    """One public sync class the manifest walks once.

    Attributes:
        cls: The class itself, taken from the public facade.
        prefix: First component of every id built from this class.
        receiver: What a caller must hold to call the members.
        state_model: Saved state that rebuilds the receiver, or ``None`` when no
            saved state is involved.
    """

    cls: type[object]
    prefix: str
    receiver: str
    state_model: type[BaseModel] | None


def _walked(
    cls: type[object],
    prefix: str,
    receiver: str,
    state_model: type[BaseModel] | None = None,
) -> WalkedClass:
    """Build a walked-class entry, keeping the table below readable."""
    return WalkedClass(
        cls=cls, prefix=prefix, receiver=receiver, state_model=state_model
    )


#: The walked surface. ``TestDataClient`` is reachable from an authenticated
#: client too and is listed once. Pager classes are walked only so
#: each member is reported as excluded; see ``EXCLUDED_CLASSES``.
WALKED_CLASSES: Final[tuple[WalkedClass, ...]] = (
    _walked(Client, "client", RECEIVER_UNAUTHENTICATED),
    _walked(AuthClient, "auth", RECEIVER_UNAUTHENTICATED),
    _walked(EncryptionClient, "encryption", RECEIVER_UNAUTHENTICATED),
    _walked(PeppolClient, "peppol", RECEIVER_UNAUTHENTICATED),
    _walked(TestDataClient, "testdata", RECEIVER_UNAUTHENTICATED),
    _walked(TemporalTestData, "temporal_testdata", RECEIVER_UNAUTHENTICATED),
    _walked(
        AuthenticatedClient,
        "authenticated",
        RECEIVER_AUTHENTICATED,
        AuthenticationResumeState,
    ),
    _walked(TokensClient, "tokens", RECEIVER_AUTHENTICATED, AuthenticationResumeState),
    _walked(
        CertificatesClient,
        "certificates",
        RECEIVER_AUTHENTICATED,
        AuthenticationResumeState,
    ),
    _walked(
        PermissionsClient,
        "permissions",
        RECEIVER_AUTHENTICATED,
        AuthenticationResumeState,
    ),
    _walked(
        InvoicesService, "invoices", RECEIVER_AUTHENTICATED, AuthenticationResumeState
    ),
    _walked(
        BatchService,
        "batch_service",
        RECEIVER_AUTHENTICATED,
        AuthenticationResumeState,
    ),
    _walked(LimitsClient, "limits", RECEIVER_AUTHENTICATED, AuthenticationResumeState),
    _walked(
        CollectiveIdentifiersClient,
        "collective_identifiers",
        RECEIVER_AUTHENTICATED,
        AuthenticationResumeState,
    ),
    _walked(
        SessionManagementClient,
        "sessions",
        RECEIVER_AUTHENTICATED,
        AuthenticationResumeState,
    ),
    _walked(
        InvoiceSessionsClient,
        "invoice_sessions",
        RECEIVER_AUTHENTICATED,
        AuthenticationResumeState,
    ),
    _walked(
        OnlineSessionClient,
        "online",
        RECEIVER_ONLINE_SESSION,
        OnlineSessionResumeState,
    ),
    _walked(
        BatchSessionClient,
        "batch",
        RECEIVER_BATCH_SESSION,
        BatchSessionResumeState,
    ),
    _walked(
        GeneratedToken,
        "generated_token",
        RECEIVER_HANDLE,
        GeneratedTokenResumeState,
    ),
    _walked(
        CertificateEnrollment,
        "certificate_enrollment",
        RECEIVER_HANDLE,
        CertificateEnrollmentResumeState,
    ),
    _walked(
        PermissionOperation,
        "permission_operation",
        RECEIVER_HANDLE,
        PermissionOperationResumeState,
    ),
    _walked(
        InvoiceSubmission,
        "invoice_submission",
        RECEIVER_HANDLE,
        InvoiceSubmissionResumeState,
    ),
    _walked(ExportJob, "export_job", RECEIVER_HANDLE, ExportResumeState),
    _walked(InvoiceSearchPager, "invoice_search", RECEIVER_HANDLE),
    _walked(
        ExportedInvoices, "exported_invoices", RECEIVER_HANDLE, ExportedInvoicesData
    ),
    _walked(Pager, "pager", RECEIVER_HANDLE),
)

#: Reason given to every member of a live pager. A pager is not saved state, so a
#: binding never holds one: it calls the collection operation again with ``cursor``.
EXCLUDED_PAGER: Final = (
    "pager receiver; call the collection operation again with its cursor"
)

#: Reason given to the batch session's own upload. The bridge rebuilds a session from
#: saved state, which never carries the payload, so the upload that takes the payload
#: explicitly is the one a binding calls.
EXCLUDED_UPLOAD_WITHOUT_PAYLOAD: Final = (
    "a rebuilt batch session holds no payload; call batch_service.upload_parts "
    "with the session state and the prepared batch"
)

#: Reason given to handle members that only the handle returned by the creating call
#: holds. The bridge rebuilds every handle from saved state, and that state never
#: carries these values, so reading them on a rebuilt handle fails.
EXCLUDED_FRESH_ONLY: Final = (
    "only the handle the creating call returns has this value; "
    "a handle rebuilt from saved state does not"
)

#: Walked classes whose every public member is excluded, with the reason that applies.
EXCLUDED_CLASSES: Final[dict[type[object], str]] = {
    Pager: EXCLUDED_PAGER,
    InvoiceSearchPager: EXCLUDED_PAGER,
}

#: Single members excluded on a class whose other members are operations.
EXCLUDED_MEMBERS: Final[dict[tuple[type[object], str], str]] = {
    (BatchSessionClient, "upload_parts"): EXCLUDED_UPLOAD_WITHOUT_PAYLOAD,
    (GeneratedToken, "token"): EXCLUDED_FRESH_ONLY,
    (GeneratedToken, "response"): EXCLUDED_FRESH_ONLY,
    (GeneratedToken, "to_sensitive_dict"): EXCLUDED_FRESH_ONLY,
    (CertificateEnrollment, "response"): EXCLUDED_FRESH_ONLY,
    (CertificateEnrollment, "timestamp"): EXCLUDED_FRESH_ONLY,
}


#: Live objects a call can hand back, and the saved state that stands in for
#: them. A binding rebuilds the object from the state instead of deserializing
#: a client, so the state is the schema and the live object never appears.
#: ``GeneratedToken``, ``Pager`` and its subclasses have their own shapes and are
#: described by ``generated_token_schema`` and ``page_schema`` instead.
RESUME_STATE_BY_CLASS: Final[dict[type[object], type[BaseModel]]] = {
    AuthenticatedClient: AuthenticationResumeState,
    OnlineSessionClient: OnlineSessionResumeState,
    BatchSessionClient: BatchSessionResumeState,
    CertificateEnrollment: CertificateEnrollmentResumeState,
    PermissionOperation: PermissionOperationResumeState,
    InvoiceSubmission: InvoiceSubmissionResumeState,
    ExportJob: ExportResumeState,
    ExportedInvoices: ExportedInvoicesData,
}

#: The one-time token never enters ``GeneratedTokenResumeState``, yet the binding
#: still has to receive it, so it travels as a sibling field of the state.
GENERATED_TOKEN_CLASS: Final[type[object]] = GeneratedToken
GENERATED_TOKEN_STATE_MODEL: Final[type[BaseModel]] = GeneratedTokenResumeState
GENERATED_TOKEN_FIELD: Final = "token"


@dataclass(frozen=True)
class DataForm:
    """The data form of a member that also accepts live objects.

    Attributes:
        live: Parameter names that carry a live object, so the manifest leaves
            them out of the operation.
        required: Names among the rest that the data form cannot be called without,
            even though the Python signature defaults them to ``None``.
    """

    live: frozenset[str]
    required: frozenset[str]


#: Members that accept exactly one of two forms: live cryptography objects, or the
#: model holding the same material as data. The manifest describes the data form
#: because a binding across a language boundary sends data, so the live parameters
#: are left out and the model that replaces them is required. That is what keeps the
#: described form the one the caller has to send. ``with_xades()`` takes a loaded
#: certificate and key, or an ``XAdESCredentials`` model built from PEM, DER or
#: PKCS#12 bytes.
DATA_FORMS: Final[dict[tuple[type[object], str], DataForm]] = {
    (AuthClient, "with_xades"): DataForm(
        live=frozenset({"cert", "private_key"}),
        required=frozenset({"credentials"}),
    ),
}

#: Collections are described as the page they hand out, never as the live pager.
#: Their operations take a cursor; pager members are excluded by ``EXCLUDED_CLASSES``.
PAGER_CLASSES: Final[tuple[type[object], ...]] = (Pager, InvoiceSearchPager)


def is_pager(annotation: object) -> bool:
    """Say whether an annotation is a pager, bare or parameterised.

    Args:
        annotation: Annotation read from a public signature.

    Returns:
        True when the annotation is ``Pager``, one of its subclasses, or a
        parameterised form of either.
    """
    return _pager_origin(annotation) is not None


def _pager_origin(annotation: object) -> type[object] | None:
    """Return the pager class an annotation stands for, if it names one."""
    candidate = annotation if isinstance(annotation, type) else type_origin(annotation)
    if not isinstance(candidate, type):
        return None
    if not issubclass(candidate, PAGER_CLASSES):
        return None
    return cast("type[object]", candidate)


def pager_item_type(annotation: object) -> object | None:
    """Return the item type a pager annotation carries.

    Args:
        annotation: A pager annotation, bare or parameterised.

    Returns:
        The item type the pager yields, an unbound type variable when the walked
        class leaves it to the caller, or ``None`` when nothing is known.
    """
    args = type_args(annotation)
    if args:
        return args[0]
    if isinstance(annotation, type):
        return _item_type_from_bases(annotation)
    return None


def _item_type_from_bases(cls: type[object]) -> object | None:
    """Follow a class' generic bases to the item type its pager was given.

    ``InvoiceSearchPager`` reaches ``InvoiceMetadata`` through
    ``Pager[InvoiceMetadata]``, which ``__orig_bases__`` keeps even though the
    inherited method annotations mention only the class' own type variable.
    """
    for candidate in cls.__mro__:
        for base in original_bases(candidate):
            origin = type_origin(base) or base
            if not isinstance(origin, type) or not issubclass(origin, PAGER_CLASSES):
                continue
            args = type_args(base)
            return args[0] if args else None
    return None


def is_client_class(annotation: object) -> bool:
    """Say whether an annotation names a client rather than a piece of data.

    Args:
        annotation: Annotation read from a public signature.

    Returns:
        True for classes defined by the client, service and raw packages, which
        are behaviour and not JSON.
    """
    if not isinstance(annotation, type) or issubclass(annotation, BaseModel):
        return False
    module = module_of(cast("object", annotation))
    return any(
        module == package or module.startswith(f"{package}.")
        for package in CLIENT_MODULES
    )


def typevar_bindings(cls: type[object]) -> dict[object, object]:
    """Map the type variables a walked class fills in to their concrete types.

    ``InvoiceSearchPager`` inherits ``Pager.page()``, whose annotation names the
    type variable rather than the model, so the binding recorded in
    ``Pager[InvoiceMetadata]`` is what turns that annotation into a schema.

    Args:
        cls: Walked class to inspect.

    Returns:
        Each type variable the class fixes, mapped to what it stands for.
    """
    bindings: dict[object, object] = {}
    for candidate in cls.__mro__:
        for base in original_bases(candidate):
            origin = type_origin(base) or base
            parameters = type_parameters(origin)
            args = type_args(base)
            if len(parameters) != len(args):
                continue
            for variable, bound in zip(parameters, args, strict=True):
                _ = bindings.setdefault(variable, bound)
    return bindings


def resume_state_for(annotation: object) -> type[BaseModel] | None:
    """Return the saved state that stands in for a live object.

    Args:
        annotation: Annotation read from a public signature.

    Returns:
        The resume-state model describing the object, or ``None`` when the
        annotation is not a live object with a saved form.
    """
    if not isinstance(annotation, type):
        return None
    return RESUME_STATE_BY_CLASS.get(annotation)
