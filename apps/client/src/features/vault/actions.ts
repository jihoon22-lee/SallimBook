/** UI intent contains only public action names and server resource IDs. */
export type WebVaultRequest =
  | { action: "setup" | "change-password" | "recover" | "rotate" }
  | { action: "view" | "edit" | "purge"; cardId: string }
  | { action: "share" | "revoke-member"; memberId: string }
  | { action: "accept-share" | "cancel-share"; offerId: string }
  | { action: "resume-rotation" | "abort-rotation"; rotationId: string };

export type WebVaultActionProps = {
  request: WebVaultRequest;
  onClose: () => void;
  onCompleted: () => void;
};
