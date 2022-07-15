:tocdepth: 1

.. sectnum::

Abstract
========

The identity management, authentication, and authorization component of the Rubin Science Platform is responsible for maintaining a list of authorized users and their associated identity information, authenticating their access to the Science Platform, and determining which services they are permitted to use.
This tech note describes the technical details of the implementation of that system.

.. note::

   This is part of a tech note series on identity management for the Rubin Science Platform.
   The other primary documents are DMTN-234_, which describes the high-level design; and SQR-069_, which provides a history and analysis of the decisions underlying the design and implementation.
   See :ref:`References <references>` for a complete list of related documents.

Implementation overview
=======================

The source of identity for users of the Science Platform varies from deployment to deployment.
The general-purpose public-facing deployment will use federated identity via InCommon.
Deployments restricted to project team members may use GitHub or local authentication mechanisms.
International Data Facility deployments may use other sources of federated identity or other local identity management systems.
The implementation of the Science Platform allows configuration of the source of user identity and supports both GitHub and OpenID Connect as protocols for determining identity.

For deployments using InCommon, the Science Platform uses CILogon_ to authenticate the user via their choice of federated identity provider.

.. _CILogon: https://www.cilogon.org/

All deployments of the Science Platform use NGINX_ via ingress-nginx_ as the ingress for all access to Science Platform components that require authentication.
The ingress invokes Gafaelfawr_ as an auth request handler to validate all requests that require authentication.
Authentication is done via bearer tokens.
Those bearer tokens may be encapsulated in a browser cookie set by Gafaelfawr or or a token provided in an ``Authorization`` header.
That auth request handler will pass (via HTTP headers) information about the authenticated user, such as username, numeric UID, and email, to the underlying Science Platform application.

.. _NGINX: https://www.nginx.com/
.. _ingress-nginx: https://kubernetes.github.io/ingress-nginx/

If the underlying application may need to make other requests on the user's behalf, or (as with the Notebook Aspect) is used interactively by the user to make subsequent requests, or if the application needs to obtain additional information about the user (such as the user's groups), Gafaelfawr will create a delegated token for that application and user.
Delegated tokens have a subset of the permissions of the user's token and an equal or shorter lifetime.
If such a token is needed, it will also be passed in an HTTP header.

Identity management
===================

The identity management component of the system maps authentication credentials to a user identity with associated metadata.
The GitHub and OpenID Connect authentication providers are also identity management providers.
With GitHub, access to the user's profile is requested as part of the OAuth 2.0 request, and user identity is retrieved via the GitHub API after authentication.
With OpenID Connect, user identity information is extracted from the JWT issued as a result of the OpenID Connect authentication flow.
With CILogon, COmanage is used, as described below.

See DMTN-225_ for more details on the metadata stored for each user, and its sources.

.. _comanage-auth:

COmanage
--------

COmanage_ is a web application with associated database and API that manages an organization of users.
It has multiple capabilities, only a few of which will be used by the Science Platform.
Its main purposes for the Science Platform are to:

.. _COmanage: https://www.incommon.org/software/comanage/

- manage the association of users with federated identities;
- assign usernames to authenticated users;
- determine the eligibility of users for Science Platform access and for roles within that access;
- manage group membership in both user-managed groups and groups managed by Vera C. Rubin Observatory; and
- store additional metadata about the user such as email, full name, and institutional affiliation.

Users will request access to the Science Platform by using the self-initiated enrollment flow in COmanage and will be approved by someone authorized to confirm who has access to the project.
In the future, we may add a mechanism to automatically grant approval based on the user's affiliation or federated authentication mechanism.
COmanage will then collect email, full name, and institutional affiliation from the user's federated authentication mechanism and store that (IDM-1104).
The user may attach multiple federated authentication mechanisms to the same account so that they can use the authentication provider of their choice (provided that it is supported by CILogon).
The user may also change their preferred email address (IDM-1101).

COmanage will expose the information it has stored for a user via LDAP.
The Science Platform will use LDAP to retrieve that information as needed.

COmanage provides a group management mechanism called COmanage Registry Groups.
This allows users to create and manage groups (IDM-2000, IDM-2002, IDM-2003, IDM-2008, IDM-4003).
We will use this group mechanism for both user-managed and institution-managed groups, and use those groups to make authorization decisions (and related decisions such as quotas) for the Science Platform.

COmanage administrators can edit user metadata using the COmanage web UI (IDM-1300).
They can also change any group, including user-managed groups (IDM-2200).

Discarded alternatives
----------------------

We considered other approaches to accepting federated identity.

Supporting InCommon directly was rejected as too complex; direct support of federated authentication is complex and requires a lot of ongoing maintenance work.

There are several services that provide federated identity as a service.
Most of them charge per user.
Given the expected number of users of the eventual production Science Platform, CILogon and its COmanage service appeared to be the least expensive option.
It also builds on a pre-existing project relationship and uses a service run by a team with extensive experience supporting federated authentication for universities and scientific collaborations.

Subsequent to that decision, we became aware of Auth0_ and its B2C authentication service, which appears to be competitive with CILogon on cost and claims to also support federated identity.
We have not done a deep investigation of that alternative.

.. _Auth0: https://auth0.com/

We considered using GitHub rather than InCommon as an identity source, and in fact used GitHub for some internal project deployments and for the DP0 preview release.
However, not every expected eventual user of the Science Platform will have a GitHub account, and GitHub lacks COmanage's support for onboarding flows, approval, and self-managed groups.
We also expect to make use of InCommon as a source of federated identity since it supports many of our expected users, and GitHub does not provide easy use of InCommon as a source of identities.

Authentication flows
====================

For deployments that use COmanage and CILogon, such as the IDF and CDF, see :ref:`New user approval <new-user>` for details on the onboarding flow.
The rest of this section assumes that the user's account record already exists.

Browser flow
------------

Implements IDM-0001 and IDM-0200.

If the user visits a Science Platform page intended for a web browser (as opposed to APIs) and is not already authenticated (either missing a cookie or having an expired cookie), they will be sent to an appropriate authentication provider.
This normally uses the `OpenID Connect`_ protocol.
(Authentications to GitHub instead use GitHub's OAuth 2.0 protocol instead.)

.. _OpenID Connect: https://openid.net/specs/openid-connect-core-1_0.html

Three different authentication providers are supported:

- GitHub_
- CILogon_
- Generic OpenID Connect support

.. _GitHub: https://docs.github.com/en/developers/apps/building-oauth-apps/authorizing-oauth-apps

In all cases, the authentication flow first redirects the user's web browser to the authentication provider (which in the case of CILogon may be multiple hops, first to CILogon and then to the underlying federated identity provider).
The user authenticates there.
Then, the browser is redirected back to the Science Platform with an authentication code, which is redeemed for credentials from the upstream authentication provider and then used to retrieve metadata about the user.
That data, in turn, is used to create a new token, which is stored in the user's cookies for the Science Platform.
This token is called a "session" token.

The authentication cookie is marked ``Secure`` and ``HttpOnly`` and is encrypted in a private key of that Science Platform instance (IDM-0008).

The data gathered for each user, and its sources, are detailed in DMTN-225_.

Token scopes
------------

Implements IDM-0104.

Each token is associated with a list of scopes.
Those scopes are used to control access to components of the Science Platform.
The scopes of a user's session token are determined from their group memberships at the point when the session token is created and a mapping from groups to scopes maintained in the Science Platform configuration.
The scopes then do not change for the lifetime of the token.

Tokens for that user created via their session token (such as :ref:`user tokens <user-tokens>` and :ref:`internal tokens <internal-tokens>`) have a subset of the scopes of the session token.
In some cases, that may be the same list of scopes, but in most cases, it will be a proper subset.

.. _user-tokens:

User token flow
---------------

Implements IDM-0202.

Users can create their own tokens and manage them via a web UI.
Such a token can be provided via an ``Authorization`` header to authenticate to Science Platform APIs via programs or other non-browser applications.
These tokens are called "user" tokens and are given a unique token name by the user on creation (which can be changed later).

The metadata about the user associated with their user tokens is the same as that associated with the session token used to create the user token.
User tokens can be limited 

See SQR-049_ for a detailed description of user tokens and the APIs used to manage them.
This system implements IDM-0100, IDM-0102, IDM-1307, and IDM-3000.

These tokens cannot be used to access COmanage or change any of the information stored there (IDM-0101).

.. _internal-tokens:

Internal tokens
---------------

Implements IDM-0103.

Bearer tokens, either in ``Authorization`` headers or in cookies, are used for all internal authentication insice the Science Platform.
Many Science Platform components will need authentication credentials for the user to act on their behalf when talking to another service.
For example, the Portal Aspect will need to make TAP queries on the user's behalf.
However, the Portal Aspect should not have unrestricted access to authenticate as the user, only restricted access to the services that it needs to talk to.
For example, the Portal Aspect should not be able to create a notebook as the user in the Notebook Aspect.

This is done with "internal" tokens, which are created as needed and passed to services that need delegated access.
These tokens have the same or shorter expiration time as the original token used to authenticate to the first service, and are automatically deleted when that token is deleted.
They are restricted to the scopes required by the service.

Usernames
---------

When using either GitHub or the generic OpenID Connect support, the username of a user within the Science Platform will match the username asserted by GitHub or the OpenID Connect provider.

When using CILogon, there is an additional level of indirection.
Because CILogon supports federated identity, it does not itself guarantee unique usernames or necessarily map an authenticated user to a username.
Instead, CILogon provides a unique identity URI (for example, ``http://cilogon.org/serverA/users/31388556``).

The mapping of that identity to a username is handled in :ref:`COmanage <comanage-auth>`.
That information is exposed to the Science Platform via LDAP.
To determine the username of a newly-authenticated user, the Science Platform therefore does an LDAP lookup for a record with a ``voPersonSoRID`` matching the CILogon identity URI in the ``sub`` claim of the JWT.
The ``uid`` attribute is the username for Science Platform purposes.

User metadata in tokens
-----------------------

Implements IDM-1100.

All Gafaelfawr authentication is done via tokens, optionally encoded inside a browser cookie.
That token has associated data stored in Redis and possibly in a PostgreSQL database.
Some data is associated with every token regardless of the identity management system.
(See SQR-049_ for all the details.)
Four pieces of data may be stored with the token or may be retrieved on the fly, depending on the identity management system:

- Full name
- Email address
- Numeric UID
- Group membership (group names and GIDs)

When GitHub or a generic OpenID Connect provider are used as the upstream source of identity information, this information is determined during initial authentication and stored with the token.
That information is then fixed for the lifetime of the token and will not reflect any changes in the upstream sources of data.

When CILogon and COmanage are used, this information is not stored with the token.
Instead, whenever that information is needed, it is retrieved from the COmanage LDAP server, or from a local cache of LDAP results whose lifetime should not exceed five minutes (IDM-0106, IDM-3002).

In either case, the same API is used to retrieve the user metadata, and user metadata is passed via the same HTTP headers, all of which are described in SQR-049_.

GitHub
------

Several behaviors of the GitHub OAuth 2.0 authentication flow warrant comment.

Organizational membership
^^^^^^^^^^^^^^^^^^^^^^^^^

When the user is sent to GitHub to perform an OAuth 2.0 authentication, they are told what information about their account the application is requesting, and are prompted for which organizational information to release.
Since we're using GitHub for group information, all organizations that should contribute to group information (via team membership) must have their data released.
GitHub supports two ways of doing this: make the organization membership public, or grant the OAuth App access to that organization's data explicitly.
GitHub allows the user to do the latter in the authorization screen during OAuth 2.0 authentication.

.. figure:: /_static/github-oauth.png
   :name: GitHub OAuth authorization screen

   The authorization screen shown by GitHub during an OAuth App authentication.
   The organizations with green checkmarks either have public membership or that OAuth App was already authorized to get organization data from them.
   The "InterNetNews" organization does not share organization membership but allows any member to authorize new OAuth Apps with the :guilabel:`Grant`.
   The "cracklib" organization does not share organization membership and requires any new authorizations be approved by administrators, which can be requested with :guilabel:`Request`.

This UI is not very obvious for users, and for security reasons we may not wish users who are not organization administrators to be able to release organization information to any OAuth App that asks.
Therefore, either organization membership should be set to public for all organizations used to control access to Science Platform deployments protected by GitHub, or someone authorized to approve OAuth Apps for each organization that will be used for group information should authenticate to the Science Platform deployment and use the :guilabel:`Grant` button to grant access to that organization's data.

If the user has authenticated with GitHub, the token returned to the OAuth App by GitHub is stored in the user's encrypted cookie.
When the user logs out, that token is used to explicitly revoke the user's OAuth App authorization at GitHub.
This forces the user to return to the OAuth App authorization screen when logging back in, which in turn will cause GitHub to release any new or changed organization information.
Without the explicit revocation, GitHub reuses the prior authorization with the organization and team data current at that time and doesn't provide data from new organizations.

Federated identities
====================

This section only applies to Science Platform deployments that use CILogon and COmanage, such as the IDF and CDF.

.. _new-user:

New user approval
-----------------

Implements IDM-0002, IDM-0003, IDM-0006, IDM-0010, IDM-0011, IDM-0013, IDM-1000, and IDM-1102.

Adding additional identities
----------------------------

Implements IDM-0004, IDM-0005, and IDM-0006.

Once the user has a COmanage account (via onboarding through some federated identity and approval by someone with access to approve new users), they can add additional federated identities.
All of those identities will then map to the same account and can be used interchangeably for Science Platform access.

To do this in COmanage, choose the "Link another account" enrollment flow from the user menu in the top right.
The user will then be asked to authenticate again, and can pick a different authentication provider from the one they're already using.
After completing that authentication, the new identity and authentication method will be added to their existing account.

The user can then see all of their linked identities from their COmanage profile page and unlink any of them if they choose.

Token UI
========

Implements IDM-0105.

The Science Platform provides a token management UI linked from the front page of each instance of the Science Platform.
That UI uses the user's session token for authentication and makes API calls to view tokens, create new user tokens, delete or modify tokens, or review token history.

Currently, the UI is implemented in React using Gatsby to package the web application, without any styling.
In the future, we expect to move it to Next.js and integrate it with the styles and visual look of the browser interface to the Science Platform.

Rejected alternatives
---------------------

We considered serving the token UI using server-rendered HTML and a separate interface from the API, but decided against it for two reasons.
First, having all changes made through the API (whether by API calls or via JavaScript) ensures that the API always has parity with the UI, ensures that every operation can be done via an API, and avoids duplicating some frontend code.
Second, other Rubin-developed components of the Science Platform are using JavaScript with a common style dictionary to design APIs, so building the token UI using similar tools will make it easier to maintain a standard look and feel.

Remaining work
==============

The following portions of the described implementation are not yet complete.

- Force two-factor authentication for administrators (IDM-0007)
- Force reauthentication to provide an affiliation (IDM-0009)
- Changing usernames (IDM-0012)
- Handling duplicate email addresses (IDM-0013)
- Disallow authentication from pending or frozen accounts (IDM-0107)
- Logging of COmanage changes to users (IDM-0200)
- Logging of authentications via Kafka to the auth history table (IDM-0203)
- Authentication history per federated identity (IDM-0204)
- Last used time of user tokens (IDM-0205)
- Email notification of federated identity and user token changes (IDM-0206)
- Freezing accounts (IDM-1001)
- Deleting accounts (IDM-1002)
- Setting an expiration date on an account (IDM-1003, IDM-1301)
- Notifying users of upcoming account expiration (IDM-1004)
- Notifying users about email address changes (IDM-1101)
- User class markers (IDM-1103, IDM-1310)
- Quotas (IDM-1200, IDM-1201, IDM-1202, IDM-1203, IDM-1303, IDM-1401, IDM-1402, IDM-2100, IDM-2101, IDM-2102, IDM-2103, IDM-2201, IDM-3003)
- Administrator verification of email addresses (IDM-1302)
- User impersonation (IDM-1304, IDM-1305, IDM-2202)
- Review newly-created accounts (IDM-1309)
- Merging accounts (IDM-1311)
- Logging of administrative actions tagged appropriately (IDM-1400, IDM-1403, IDM-1404)
- Affiliation-based groups (IDM-2001)
- Group name restrictions (IDM-2004)
- Expiration of group membership (IDM-2005)
- Group renaming while preserving GID (IDM-2006)
- Correct handling of group deletion (IDM-2007)
- Groups owned by other groups (IDM-2009)
- Logging of group changes (IDM-2300, IDM-2301, IDM-2302, IDM-2303, IDM-2304, IDM-2305, IDM-4002)
- API to COmanage (IDM-3001)
- Scale testing (IDM-4000)
- Scaling of group membership (IDM-4001)

.. _references:

References
==========

Design
------

SQR-044_
    Requirements for the identity management system.
    This document is now incompete and partly out of date, but still provides useful detail of requirements that have not yet been incorporated into the design.

SQR-049_
    Detailed design of the token management system for the Science Platform, including its API and storage model.
    Not all of the elements of this design have been implemented, and some of them may be modified before implementation.

DMTN-225_
    Metadata gathered and stored for each user, including constraints such as valid username and group name patterns and UID and GID ranges.

DMTN-234_
    High-level design for the Rubin Science Platform identity management system.
    This is the document to read first to understand the overall system.

.. _SQR-044: https://sqr-044.lsst.io/
.. _SQR-049: https://sqr-049.lsst.io/
.. _DMTN-225: https://dmtn-225.lsst.io/
.. _DMTN-234: https://dmtn-225.lsst.io/

Security
--------

SQR-051_
    Discussion of credential leaks from the authentication system to backend services, and possible fixes and mitigations.

DMTN-193_
    General discussion of web security for the Science Platform, which among other topics suggests additional design considerations for the Science Platform ingress, authentication layer, and authorization layer.

.. _SQR-051: https://sqr-051.lsst.io/
.. _DMTN-193: https://dmtn-193.lsst.io/

Implementation details
----------------------

DMTN-235_
    Lists the token scopes used by the identity management system, defines them, and documents the services to which they grant access.

SQR-055_
    How to configure COmanage for the needs of the identity management component of the Science Platform.

.. _DMTN-235: https://dmtn-235.lsst.io/
.. _SQR-055: https://sqr-055.lsst.io/

Operations
----------

Gafaelfawr_
    The primary component of the identity management system.
    Its documentation convers operational issues such as configuration and maintenance.

Phalanx_
    The configuration and deployment infrastructure for the Science Platform.
    Its documentation includes operational details on how to configure services to correctly use the identity management system.

.. _Gafaelfawr: https://gafaelfawr.lsst.io/
.. _Phalanx: https://phalanx.lsst.io/

Project documents
-----------------

These are higher-level documents discussing Vera C. Rubin Observatory and the Science Platform as a whole that contain information relevant to the design and implementation of the identity management system.

LDM-554_
    General requirements document for the Science Platform.
    This includes some requirements for the identity management system.

LSE-279_
    General discussion of authentication and authorization for Vera C. Rubin Observatory.
    This is primarily a definition of terms and very high-level requirements for identity management.
    The group naming scheme described in this document has been replaced with the scheme in DMTN-235_.

LPM-121_
    Information security policy and procedures for Vera C. Rubin Observatory.
    This document is primarily concerned with defining roles and responsibilities.

RDO-013_
    The Vera C. Rubin Observatory Data Policy, which defines who will have access to Rubin Observatory data.

.. _LDM-554: https://ldm-554.lsst.io/
.. _LSE-279: https://docushare.lsst.org/docushare/dsweb/Get/LSE-279
.. _LPM-121: https://docushare.lsst.org/docushare/dsweb/Get/LPM-121
.. _RDO-013: https://docushare.lsst.org/docushare/dsweb/Get/RDO-13

Vendor evaluations
------------------

SQR-045_
    Evaluation of CILogon COmanage for use as the basis of user identity management and group management.

SQR-046_
    Evaluation of GitHub for use as the basis of user identity management and group management.

.. _SQR-045: https://sqr-045.lsst.io/
.. _SQR-046: https://sqr-046.lsst.io/

History
-------

DMTN-094_
    Original design document for the identity management system, now superseded and of historical interest only.

DMTN-116_
    Original implementation strategy for the identity management system, now superseded and of historical interest only.

SQR-039_
    Problem statement and proposed redesign for the identity management system.
    This document contains a detailed discussion of the decision not to use :abbr:`JWTs (JSON Web Tokens)` in the authentication system, and to keep authorization information such as group credentials out of the authentication tokens.

.. _SQR-039: https://sqr-039.lsst.io/
.. _DMTN-094: https://dmtn-094.lsst.io/
.. _DMTN-116: https://dmtn-116.lsst.io/
