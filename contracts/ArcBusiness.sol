// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
}

/// @title ArcBusiness — "Stripe for Agreements" on Arc
/// @notice Milestone-based USDC escrow between a client and a service provider.
///         USDC on Arc Testnet: 0x3600000000000000000000000000000000000000 (6 decimals).
contract ArcBusiness {
    IERC20 public constant USDC = IERC20(0x3600000000000000000000000000000000000000);
    uint256 public constant DISPUTE_WINDOW = 48 hours;

    enum MilestoneStatus { Created, Funded, Released, Disputed, Refunded }

    struct Milestone {
        string description;
        uint256 amount;        // USDC, 6 decimals
        uint256 deadline;      // unix timestamp
        uint256 disputedAt;    // when dispute opened (0 = none)
        MilestoneStatus status;
    }

    struct Agreement {
        address client;        // party1: funds milestones
        address provider;      // party2: receives payments
        string title;
        uint256 totalAmount;   // USDC, 6 decimals
        uint256 createdAt;
        uint256 milestoneCount;
        bool active;
    }

    uint256 public agreementCount;
    mapping(uint256 => Agreement) public agreements;
    mapping(uint256 => mapping(uint256 => Milestone)) public milestones;

    event AgreementCreated(uint256 indexed agreementId, address indexed client, address indexed provider, string title, uint256 totalAmount);
    event MilestoneCreated(uint256 indexed agreementId, uint256 indexed milestoneId, string description, uint256 amount, uint256 deadline);
    event USDCLocked(uint256 indexed agreementId, uint256 indexed milestoneId, uint256 amount);
    event PaymentReleased(uint256 indexed agreementId, uint256 indexed milestoneId, address indexed provider, uint256 amount);
    event WorkSubmitted(uint256 indexed agreementId, uint256 indexed milestoneId, address indexed provider);
    event DisputeOpened(uint256 indexed agreementId, uint256 indexed milestoneId, address indexed by);
    event Refunded(uint256 indexed agreementId, uint256 indexed milestoneId, address indexed client, uint256 amount);

    modifier onlyParty(uint256 agreementId) {
        Agreement storage a = agreements[agreementId];
        require(msg.sender == a.client || msg.sender == a.provider, "not a party");
        _;
    }

    function createAgreement(address party2, string calldata title, uint256 totalAmount)
        external
        returns (uint256 agreementId)
    {
        require(party2 != address(0) && party2 != msg.sender, "invalid party2");
        require(totalAmount > 0, "amount = 0");

        agreementId = agreementCount++;
        agreements[agreementId] = Agreement({
            client: msg.sender,
            provider: party2,
            title: title,
            totalAmount: totalAmount,
            createdAt: block.timestamp,
            milestoneCount: 0,
            active: true
        });
        emit AgreementCreated(agreementId, msg.sender, party2, title, totalAmount);
    }

    function createMilestone(uint256 agreementId, string calldata description, uint256 amount, uint256 deadline)
        external
        onlyParty(agreementId)
        returns (uint256 milestoneId)
    {
        Agreement storage a = agreements[agreementId];
        require(a.active, "inactive agreement");
        require(amount > 0, "amount = 0");
        require(deadline > block.timestamp, "deadline in past");

        milestoneId = a.milestoneCount++;
        milestones[agreementId][milestoneId] = Milestone({
            description: description,
            amount: amount,
            deadline: deadline,
            disputedAt: 0,
            status: MilestoneStatus.Created
        });
        emit MilestoneCreated(agreementId, milestoneId, description, amount, deadline);
    }

    /// @notice Client escrows USDC for a milestone. Requires prior USDC approve().
    function lockUSDC(uint256 agreementId, uint256 milestoneId) external {
        Agreement storage a = agreements[agreementId];
        Milestone storage m = milestones[agreementId][milestoneId];
        require(msg.sender == a.client, "only client");
        require(m.status == MilestoneStatus.Created, "not fundable");

        m.status = MilestoneStatus.Funded;
        require(USDC.transferFrom(msg.sender, address(this), m.amount), "transferFrom failed");
        emit USDCLocked(agreementId, milestoneId, m.amount);
    }

    /// @notice Client releases escrowed USDC to the provider.
    function releasePayment(uint256 agreementId, uint256 milestoneId) external {
        Agreement storage a = agreements[agreementId];
        Milestone storage m = milestones[agreementId][milestoneId];
        require(msg.sender == a.client, "only client");
        require(m.status == MilestoneStatus.Funded, "not funded");

        m.status = MilestoneStatus.Released;
        require(USDC.transfer(a.provider, m.amount), "transfer failed");
        emit PaymentReleased(agreementId, milestoneId, a.provider, m.amount);
    }

    /// @notice Provider marks work as delivered on a funded milestone (deliverable
    ///         details are stored off-chain). Escrowed funds are untouched; the
    ///         client still calls releasePayment() or openDispute().
    function submitWork(uint256 agreementId, uint256 milestoneId) external {
        Agreement storage a = agreements[agreementId];
        Milestone storage m = milestones[agreementId][milestoneId];
        require(msg.sender == a.provider, "only provider");
        require(m.status == MilestoneStatus.Funded, "not funded");
        emit WorkSubmitted(agreementId, milestoneId, msg.sender);
    }

    /// @notice Either party opens a dispute on a funded milestone.
    function openDispute(uint256 agreementId, uint256 milestoneId) external onlyParty(agreementId) {
        Milestone storage m = milestones[agreementId][milestoneId];
        require(m.status == MilestoneStatus.Funded, "not funded");

        m.status = MilestoneStatus.Disputed;
        m.disputedAt = block.timestamp;
        emit DisputeOpened(agreementId, milestoneId, msg.sender);
    }

    /// @notice After 48h of unresolved dispute, anyone can trigger the refund to the client.
    function claimRefund(uint256 agreementId, uint256 milestoneId) external {
        Agreement storage a = agreements[agreementId];
        Milestone storage m = milestones[agreementId][milestoneId];
        require(m.status == MilestoneStatus.Disputed, "not disputed");
        require(block.timestamp >= m.disputedAt + DISPUTE_WINDOW, "dispute window open");

        m.status = MilestoneStatus.Refunded;
        require(USDC.transfer(a.client, m.amount), "transfer failed");
        emit Refunded(agreementId, milestoneId, a.client, m.amount);
    }

    /// @notice Provider may resolve a dispute in the client's favor immediately (refund without waiting 48h).
    function resolveDisputeRefund(uint256 agreementId, uint256 milestoneId) external {
        Agreement storage a = agreements[agreementId];
        Milestone storage m = milestones[agreementId][milestoneId];
        require(msg.sender == a.provider, "only provider");
        require(m.status == MilestoneStatus.Disputed, "not disputed");

        m.status = MilestoneStatus.Refunded;
        require(USDC.transfer(a.client, m.amount), "transfer failed");
        emit Refunded(agreementId, milestoneId, a.client, m.amount);
    }

    /// @notice Client may resolve a dispute in the provider's favor (release despite dispute).
    function resolveDisputeRelease(uint256 agreementId, uint256 milestoneId) external {
        Agreement storage a = agreements[agreementId];
        Milestone storage m = milestones[agreementId][milestoneId];
        require(msg.sender == a.client, "only client");
        require(m.status == MilestoneStatus.Disputed, "not disputed");

        m.status = MilestoneStatus.Released;
        require(USDC.transfer(a.provider, m.amount), "transfer failed");
        emit PaymentReleased(agreementId, milestoneId, a.provider, m.amount);
    }

    // ---- Views ----

    function getAgreement(uint256 agreementId)
        external
        view
        returns (address client, address provider, string memory title, uint256 totalAmount, uint256 createdAt, uint256 milestoneCount_, bool active)
    {
        Agreement storage a = agreements[agreementId];
        return (a.client, a.provider, a.title, a.totalAmount, a.createdAt, a.milestoneCount, a.active);
    }

    function getMilestone(uint256 agreementId, uint256 milestoneId)
        external
        view
        returns (string memory description, uint256 amount, uint256 deadline, uint256 disputedAt, MilestoneStatus status)
    {
        Milestone storage m = milestones[agreementId][milestoneId];
        return (m.description, m.amount, m.deadline, m.disputedAt, m.status);
    }

    /// @notice Whether a disputed milestone is past the 48h window and refundable.
    function isRefundable(uint256 agreementId, uint256 milestoneId) external view returns (bool) {
        Milestone storage m = milestones[agreementId][milestoneId];
        return m.status == MilestoneStatus.Disputed && block.timestamp >= m.disputedAt + DISPUTE_WINDOW;
    }
}
